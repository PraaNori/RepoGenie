"""
Deterministic Repository Workflow Candidate Discovery and Ranking.

Identifies application workflow candidates by analyzing:
1. High-confidence EntryPointCandidate records.
2. Architectural components classified as API routes or entry points.
3. High-out-degree functions in top important files for library repositories.
4. Directional CallGraph edges (max depth 4, cycle protection).

Strictly enforces:
- Max 2 AI semantic candidates.
- Max 2 structural call chain candidates.
- Explicit omitted candidate reporting.
- Never uses dependency imports as execution transitions.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from ....models.schemas import (
    CallGraph,
    CallGraphEdge,
    EntryPointCandidate,
    ParsedFile,
    RepositoryKnowledge,
)
from .schemas import CallSiteEvidence

logger = logging.getLogger(__name__)


class CandidateCallNode(BaseModel):
    """Represents a directional call step along a discovered candidate workflow path."""
    caller_file: str
    caller_symbol: str
    callee_file: str
    callee_symbol: str
    call_name: str
    call_site_line: int
    call_site_col: Optional[int] = None
    call_graph_edge_id: str
    call_site_id: str
    is_internal: bool = True
    hop_depth: int = 1


class DiscoveredWorkflowCandidate(BaseModel):
    """A grounded candidate workflow discovered from directional CallGraph traversal."""
    candidate_id: str
    name: str
    category: str                          # "user_request", "api_handling", "initialization", "business_logic", "library_flow"
    entry_symbol: str
    entry_file: str
    trigger: str
    call_chain: List[CandidateCallNode] = Field(default_factory=list)
    participating_files: List[str] = Field(default_factory=list)
    participating_symbols: List[str] = Field(default_factory=list)
    score: float = 0.0
    is_library_flow: bool = False
    is_recursive: bool = False
    seed_type: str = "entry_point"          # "entry_point", "api_route", "library_symbol"
    omission_reasons: List[str] = Field(default_factory=list)


class CandidateDiscoveryResult(BaseModel):
    """Result of candidate discovery partitioned into AI candidates, structural chains, and omitted list."""
    selected_ai_candidates: List[DiscoveredWorkflowCandidate] = Field(default_factory=list, max_length=2)
    structural_call_chain_candidates: List[DiscoveredWorkflowCandidate] = Field(default_factory=list, max_length=2)
    omitted_candidate_workflows: List[str] = Field(default_factory=list)
    total_candidates_discovered: int = 0


class WorkflowCandidateDiscoverer:
    """
    Deterministically traverses directional CallGraph edges from grounded entry points
    and architectural components to construct candidate workflows.
    """

    MAX_DEPTH = 4
    MAX_AI_CANDIDATES = 2
    MAX_STRUCTURAL_CHAINS = 2
    MAX_BRANCHES_PER_NODE = 2
    MAX_VISITED_NODES_PER_SEED = 25
    MAX_PATHS_EXPLORED_PER_SEED = 50
    MAX_EDGES_EXAMINED_PER_RUN = 500

    def discover_candidates(self, knowledge: RepositoryKnowledge) -> CandidateDiscoveryResult:
        """Discovers, traces, ranks, and deduplicates workflow candidates from RepositoryKnowledge."""
        call_graph = getattr(getattr(knowledge, "architecture", None), "call_graph", None)
        if not call_graph or not getattr(call_graph, "edges", None):
            return CandidateDiscoveryResult()

        # Build fast lookup indexes from CallGraph and parsed files
        edge_index = self._build_edge_index(call_graph.edges)
        parsed_files_map = {
            f.file_path.replace("\\", "/").strip().lstrip("/"): f
            for f in getattr(getattr(knowledge, "code_structure", None), "files", [])
        }

        # Shared traversal stats to bound global work across seeds
        traversal_stats: Dict[str, int] = {"edges_examined": 0}
        omitted_reasons: List[str] = []

        # 1. Collect candidate seeds
        raw_candidates: List[DiscoveredWorkflowCandidate] = []
        seen_entry_keys: Set[Tuple[str, str]] = set()

        # Seed Tier 1: High-confidence Entry Points
        entry_points = getattr(knowledge, "entry_points", []) or []
        for ep in entry_points:
            if traversal_stats["edges_examined"] >= self.MAX_EDGES_EXAMINED_PER_RUN:
                omitted_reasons.append(
                    f"Candidate exploration budget reached ({self.MAX_EDGES_EXAMINED_PER_RUN} edges examined); remaining entry points omitted."
                )
                break
            seeds = self._extract_seeds_from_entry_point(ep, parsed_files_map)
            for file_path, symbol_name, trigger in seeds:
                key = (file_path, symbol_name)
                if key in seen_entry_keys:
                    continue
                seen_entry_keys.add(key)
                cand = self._trace_candidate_path(
                    file_path=file_path,
                    symbol_name=symbol_name,
                    trigger=trigger,
                    category="user_request" if "cli" in trigger.lower() or "command" in trigger.lower() else "initialization",
                    seed_type="entry_point",
                    edge_index=edge_index,
                    confidence_weight=3.0 if getattr(ep, "confidence", "medium") == "high" else 2.0,
                    traversal_stats=traversal_stats,
                )
                if cand:
                    raw_candidates.append(cand)

        # Seed Tier 2: API Routes from Architectural Components
        arch_components = getattr(getattr(knowledge, "architecture", None), "components", []) or []
        for comp in arch_components:
            if traversal_stats["edges_examined"] >= self.MAX_EDGES_EXAMINED_PER_RUN:
                omitted_reasons.append(
                    f"Candidate exploration budget reached ({self.MAX_EDGES_EXAMINED_PER_RUN} edges examined); remaining API components omitted."
                )
                break
            if getattr(comp, "category", "") in ("api_route", "entry_point"):
                norm_path = comp.file_path.replace("\\", "/").strip().lstrip("/")
                if norm_path in parsed_files_map:
                    pf = parsed_files_map[norm_path]
                    for fn in pf.functions[:2]:  # Sample top public route handlers
                        if fn.name.startswith("_"):
                            continue
                        key = (norm_path, fn.name)
                        if key in seen_entry_keys:
                            continue
                        seen_entry_keys.add(key)
                        cand = self._trace_candidate_path(
                            file_path=norm_path,
                            symbol_name=fn.name,
                            trigger=f"Incoming HTTP request routed to {fn.name}()",
                            category="api_handling",
                            seed_type="api_route",
                            edge_index=edge_index,
                            confidence_weight=2.5,
                            traversal_stats=traversal_stats,
                        )
                        if cand:
                            raw_candidates.append(cand)

        # Seed Tier 3: Library Repositories (High out-degree symbols in important files)
        if len(raw_candidates) < (self.MAX_AI_CANDIDATES + self.MAX_STRUCTURAL_CHAINS):
            library_seeds = self._extract_library_seeds(knowledge, edge_index, seen_entry_keys)
            for file_path, symbol_name, trigger in library_seeds:
                if traversal_stats["edges_examined"] >= self.MAX_EDGES_EXAMINED_PER_RUN:
                    omitted_reasons.append(
                        f"Candidate exploration budget reached ({self.MAX_EDGES_EXAMINED_PER_RUN} edges examined); remaining library symbols omitted."
                    )
                    break
                key = (file_path, symbol_name)
                if key in seen_entry_keys:
                    continue
                seen_entry_keys.add(key)
                cand = self._trace_candidate_path(
                    file_path=file_path,
                    symbol_name=symbol_name,
                    trigger=trigger,
                    category="business_logic",
                    seed_type="library_symbol",
                    edge_index=edge_index,
                    confidence_weight=1.5,
                    is_library_flow=True,
                    traversal_stats=traversal_stats,
                )
                if cand:
                    raw_candidates.append(cand)

        # 2. Deduplicate candidates (protect distinct workflows with different terminal leaves)
        deduplicated, dedup_reasons = self._deduplicate_candidates(raw_candidates)

        # 3. Sort by deterministic score descending
        deduplicated.sort(key=lambda c: (c.score, len(c.call_chain), len(c.participating_files)), reverse=True)

        total_discovered = len(deduplicated)
        ai_candidates = deduplicated[: self.MAX_AI_CANDIDATES]
        structural_candidates = deduplicated[self.MAX_AI_CANDIDATES : self.MAX_AI_CANDIDATES + self.MAX_STRUCTURAL_CHAINS]
        
        # Combine deduplication reasons, budget omissions, and per-candidate omission messages
        budget_omitted = [
            f"Candidate '{c.name}' ({c.entry_file}:{c.entry_symbol}) omitted due to workflow budget limit."
            for c in deduplicated[self.MAX_AI_CANDIDATES + self.MAX_STRUCTURAL_CHAINS :]
        ]
        all_omitted = dedup_reasons + omitted_reasons + budget_omitted

        return CandidateDiscoveryResult(
            selected_ai_candidates=ai_candidates,
            structural_call_chain_candidates=structural_candidates,
            omitted_candidate_workflows=all_omitted,
            total_candidates_discovered=total_discovered,
        )

    def _build_edge_index(self, edges: List[CallGraphEdge]) -> Dict[str, List[CallGraphEdge]]:
        """Indexes CallGraph edges by caller node ID and caller symbol."""
        index: Dict[str, List[CallGraphEdge]] = {}
        for edge in edges:
            src = edge.caller.replace("\\", "/").strip().lstrip("/")
            index.setdefault(src, []).append(edge)
            # Index by bare symbol as fallback if caller matches "file:symbol"
            if ":" in src:
                bare_sym = src.split(":")[-1]
                index.setdefault(bare_sym, []).append(edge)
        return index

    def _extract_seeds_from_entry_point(
        self, ep: EntryPointCandidate, parsed_files: Dict[str, ParsedFile]
    ) -> List[Tuple[str, str, str]]:
        """Extracts (file_path, symbol_name, trigger_description) from EntryPointCandidate."""
        norm_path = ep.file_path.replace("\\", "/").strip().lstrip("/")
        seeds: List[Tuple[str, str, str]] = []

        entry_type = getattr(ep, "entry_type", "")
        symbol = getattr(ep, "symbol_or_command", "")

        trigger = "Application invoked via entry point command."
        if "main_guard" in entry_type:
            trigger = "CLI or process executed via Python main guard."
        elif "framework_app" in entry_type:
            trigger = "Framework server or application instance dispatched."

        if symbol and norm_path in parsed_files:
            seeds.append((norm_path, symbol, trigger))
        elif norm_path in parsed_files:
            pf = parsed_files[norm_path]
            # Look for common entry function names: main, cli, run, app
            for fn in pf.functions:
                if fn.name in ("main", "cli", "run", "start", "execute"):
                    return [(norm_path, fn.name, trigger)]
            for cls in pf.classes:
                if cls.name in ("Command", "App", "Application", "Server"):
                    return [(norm_path, cls.name, trigger)]
            if pf.functions:
                seeds.append((norm_path, pf.functions[0].name, trigger))

        return seeds

    def _extract_library_seeds(
        self,
        knowledge: RepositoryKnowledge,
        edge_index: Dict[str, List[CallGraphEdge]],
        seen_keys: Set[Tuple[str, str]],
    ) -> List[Tuple[str, str, str]]:
        """Finds high-value library entry functions with substantial outgoing call relationships."""
        seeds: List[Tuple[str, str, str]] = []
        important_files = getattr(knowledge, "important_files", []) or []

        for imp in important_files[:5]:
            norm_path = imp.relative_path.replace("\\", "/").strip().lstrip("/")
            for caller_id, edges in edge_index.items():
                if caller_id.startswith(f"{norm_path}:"):
                    sym = caller_id.split(":")[-1]
                    key = (norm_path, sym)
                    if key not in seen_keys and len(edges) > 0:
                        seeds.append((norm_path, sym, f"Library invocation of public API function {sym}()"))
                        if len(seeds) >= 3:
                            return seeds

        return seeds

    def _trace_candidate_path(
        self,
        file_path: str,
        symbol_name: str,
        trigger: str,
        category: str,
        seed_type: str,
        edge_index: Dict[str, List[CallGraphEdge]],
        confidence_weight: float,
        is_library_flow: bool = False,
        traversal_stats: Optional[Dict[str, int]] = None,
    ) -> Optional[DiscoveredWorkflowCandidate]:
        """Traces directional CallGraph edges starting at file_path:symbol_name up to MAX_DEPTH."""
        norm_file = file_path.replace("\\", "/").strip().lstrip("/")
        root_node_id = f"{norm_file}:{symbol_name}"

        call_chain: List[CandidateCallNode] = []
        visited_nodes: Set[str] = {root_node_id}
        participating_files: Set[str] = {norm_file}
        participating_symbols: Set[str] = {symbol_name}
        omission_reasons: List[str] = []
        is_recursive = False
        paths_explored = 0

        # DFS stack: (current_node_id, current_depth)
        frontier = [(root_node_id, 1)]

        while frontier and len(call_chain) < 5:
            if len(visited_nodes) >= self.MAX_VISITED_NODES_PER_SEED:
                omission_reasons.append(
                    f"Per-seed visited node limit reached ({self.MAX_VISITED_NODES_PER_SEED} nodes visited); remaining path omitted."
                )
                break

            if paths_explored >= self.MAX_PATHS_EXPLORED_PER_SEED:
                omission_reasons.append(
                    f"Per-seed path exploration limit reached ({self.MAX_PATHS_EXPLORED_PER_SEED} paths explored); remaining path omitted."
                )
                break

            curr_id, depth = frontier.pop(0)
            paths_explored += 1

            if depth > self.MAX_DEPTH:
                continue

            outgoing = edge_index.get(curr_id, [])
            if not outgoing and ":" in curr_id:
                bare = curr_id.split(":")[-1]
                outgoing = edge_index.get(bare, [])

            # Deterministic ordering: prioritize resolved internal calls, then source line number, then callee
            outgoing_sorted = sorted(
                outgoing,
                key=lambda e: (
                    e.resolution_status != "resolved_internal",
                    getattr(e.evidence, "line_number", 0) or 0,
                    e.callee,
                    e.call_name or "",
                ),
            )

            # Limit fan-out to MAX_BRANCHES_PER_NODE (2 primary calls per step)
            for edge in outgoing_sorted[: self.MAX_BRANCHES_PER_NODE]:
                if traversal_stats is not None:
                    traversal_stats["edges_examined"] = traversal_stats.get("edges_examined", 0) + 1
                    if traversal_stats["edges_examined"] >= self.MAX_EDGES_EXAMINED_PER_RUN:
                        omission_reasons.append(
                            f"Global edge examination budget reached ({self.MAX_EDGES_EXAMINED_PER_RUN} edges); remaining exploration halted."
                        )
                        break

                tgt = edge.callee.replace("\\", "/").strip().lstrip("/")
                if tgt in visited_nodes:
                    is_recursive = True
                    continue

                visited_nodes.add(tgt)
                tgt_file = tgt.split(":")[0] if ":" in tgt else norm_file
                tgt_sym = tgt.split(":")[-1] if ":" in tgt else tgt

                participating_files.add(tgt_file)
                participating_symbols.add(tgt_sym)

                line = getattr(edge.evidence, "line_number", None) or 1
                col = getattr(edge.evidence, "start_column", None)

                curr_file = curr_id.split(":")[0] if ":" in curr_id else norm_file
                curr_sym = curr_id.split(":")[-1] if ":" in curr_id else curr_id

                edge_id = CallSiteEvidence.format_edge_id(curr_file, curr_sym, tgt_file, tgt_sym)
                site_id = CallSiteEvidence.format_site_id(curr_file, curr_sym, tgt_file, tgt_sym, line, col)

                call_chain.append(
                    CandidateCallNode(
                        caller_file=curr_file,
                        caller_symbol=curr_sym,
                        callee_file=tgt_file,
                        callee_symbol=tgt_sym,
                        call_name=edge.call_name or tgt_sym,
                        call_site_line=line,
                        call_site_col=col,
                        call_graph_edge_id=edge_id,
                        call_site_id=site_id,
                        is_internal=(edge.resolution_status == "resolved_internal"),
                        hop_depth=depth,
                    )
                )

                if depth + 1 <= self.MAX_DEPTH:
                    frontier.append((tgt, depth + 1))

        # Calculate deterministic composite score using all 5 approved criteria:
        # 1. Entry-point confidence / centrality
        c_weight = confidence_weight

        # 2. Call-chain depth (longer chains preferred up to depth 4)
        depth_score = min(len(call_chain), self.MAX_DEPTH) * 1.5

        # 3. Relevant-call quality (proportion of calls that are internal/resolved vs trivial builtins)
        internal_calls = sum(1 for c in call_chain if c.is_internal)
        quality_score = (internal_calls / max(len(call_chain), 1)) * 3.0

        # 4. Unique participating files (multi-file workflows preferred over single-file scripts)
        comp_diversity_score = min(len(participating_files), 4) * 2.0

        # 5. Evidence completeness (proportion of steps with verified call-site line numbers)
        ev_complete = sum(1 for c in call_chain if c.call_site_line > 0)
        evidence_score = (ev_complete / max(len(call_chain), 1)) * 2.0

        # Library penalty to prevent library utility functions from outranking meaningful application workflows
        library_penalty = 1.0 if is_library_flow else 0.0

        score = c_weight + depth_score + quality_score + comp_diversity_score + evidence_score - library_penalty

        cand_id = f"candidate-{norm_file.replace('/', '_')}-{symbol_name}".lower()
        title_name = f"{symbol_name.capitalize()} Workflow" if not is_library_flow else f"{symbol_name} Library Flow"

        return DiscoveredWorkflowCandidate(
            candidate_id=cand_id,
            name=title_name,
            category=category,
            entry_symbol=symbol_name,
            entry_file=norm_file,
            trigger=trigger,
            call_chain=call_chain,
            participating_files=sorted(list(participating_files)),
            participating_symbols=sorted(list(participating_symbols)),
            score=round(score, 2),
            is_library_flow=is_library_flow,
            is_recursive=is_recursive,
            seed_type=seed_type,
            omission_reasons=omission_reasons,
        )

    def _deduplicate_candidates(
        self, candidates: List[DiscoveredWorkflowCandidate]
    ) -> Tuple[List[DiscoveredWorkflowCandidate], List[str]]:
        """
        Deduplicates candidate workflows sharing the same entry point, >=70% call edges,
        AND equivalent terminal/leaf operations.
        Preserves distinct workflows with different downstream operations or target components.
        """
        deduped: List[DiscoveredWorkflowCandidate] = []
        dedup_reasons: List[str] = []

        for cand in candidates:
            is_dup = False
            for existing in deduped:
                # Same entry point and high edge overlap
                if cand.entry_file == existing.entry_file and cand.entry_symbol == existing.entry_symbol:
                    edges_cand = {c.call_graph_edge_id for c in cand.call_chain}
                    edges_exist = {c.call_graph_edge_id for c in existing.call_chain}
                    if edges_cand and edges_exist:
                        overlap = len(edges_cand.intersection(edges_exist)) / max(len(edges_cand), len(edges_exist))

                        # Compare terminal / leaf operations
                        cand_leaf = (cand.call_chain[-1].callee_file, cand.call_chain[-1].callee_symbol) if cand.call_chain else None
                        exist_leaf = (existing.call_chain[-1].callee_file, existing.call_chain[-1].callee_symbol) if existing.call_chain else None

                        # Only deduplicate if edge overlap >= 70% AND terminal leaf operations match
                        if overlap >= 0.70 and cand_leaf == exist_leaf:
                            is_dup = True
                            leaf_desc = cand_leaf[1] if cand_leaf else "none"
                            if cand.score > existing.score:
                                dedup_reasons.append(
                                    f"Candidate '{existing.name}' ({existing.entry_file}:{existing.entry_symbol}) deduplicated into '{cand.name}' "
                                    f"(edge overlap: {overlap:.0%}, identical terminal operation '{leaf_desc}')."
                                )
                                deduped.remove(existing)
                                deduped.append(cand)
                            else:
                                dedup_reasons.append(
                                    f"Candidate '{cand.name}' ({cand.entry_file}:{cand.entry_symbol}) deduplicated into '{existing.name}' "
                                    f"(edge overlap: {overlap:.0%}, identical terminal operation '{leaf_desc}')."
                                )
                            break
            if not is_dup:
                deduped.append(cand)

        return deduped, dedup_reasons


workflow_candidate_discoverer = WorkflowCandidateDiscoverer()
