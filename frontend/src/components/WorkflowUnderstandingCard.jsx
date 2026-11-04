import React, { useState } from 'react';
import {
  Workflow,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  Cpu,
  Clock,
  Zap,
  RefreshCw,
  Layers,
  ArrowRight,
  ArrowDown,
  Database,
  Globe,
  FileCode,
  ChevronDown,
  ChevronUp,
  Boxes,
  Activity,
  Check,
  X,
  Info,
  GitBranch,
  Network,
  HelpCircle,
  Share2,
  Terminal,
} from 'lucide-react';

/**
 * Sanitizes local filesystem paths to ensure internal machine paths are never exposed.
 */
function sanitizePath(filePath) {
  if (!filePath || typeof filePath !== 'string') return '';
  return filePath
    .replace(/^.*\/repo_cache\/[^\/]+\//, '<REPO_ROOT>/')
    .replace(/^\/Users\/[^\/]+(\/[^\/]+)*\/([^\/]+\/[^\/]+)$/, '<REPO_ROOT>/$2')
    .replace(/^\/home\/[^\/]+(\/[^\/]+)*\/([^\/]+\/[^\/]+)$/, '<REPO_ROOT>/$2')
    .replace(/^\/tmp\/[^\/]+\//, '<REPO_ROOT>/');
}

export default function WorkflowUnderstandingCard({
  workflowUnderstanding,
  isLoading,
  onGenerate,
  error,
  isPrerequisiteReady = true,
  readOnly = false,
  defaultTab = 'workflows',
}) {
  const [activeTab, setActiveTab] = useState(defaultTab); // 'workflows' | 'data_flows' | 'operations' | 'structural_chains' | 'evidence_limitations'
  const [selectedWorkflowIdx, setSelectedWorkflowIdx] = useState(0);
  const [expandedStepIdx, setExpandedStepIdx] = useState(null);
  const [operationFilter, setOperationFilter] = useState('all'); // 'all' | 'db_read' | 'db_write' | 'db_delete' | 'http'

  // 1. Not yet generated and not loading
  if (!workflowUnderstanding && !isLoading) {
    return (
      <div className="bg-gradient-to-br from-violet-50/70 via-white to-indigo-50/50 rounded-2xl border border-violet-200 p-6 sm:p-8 shadow-sm mb-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-violet-600 text-white flex items-center justify-center mx-auto mb-4 shadow-md shadow-violet-200">
          <Workflow className="w-6 h-6" />
        </div>
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-violet-100 text-violet-800 border border-violet-200 mb-3">
          <Sparkles className="w-3.5 h-3.5 text-violet-600" />
          <span>Milestone 3.4 & 3.5 • Application Workflow & Data-Flow</span>
        </div>
        <h3 className="text-lg font-bold text-slate-900 mb-2">
          Discover End-to-End Application Workflows
        </h3>
        <p className="text-sm text-slate-600 max-w-xl mx-auto mb-6 leading-relaxed">
          Reconstruct directional execution paths, trace runtime data flows across components,
          and verify storage and external API operations using deterministic AST control-flow evidence.
        </p>

        {error && (
          <div className="max-w-md mx-auto mb-5 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2 text-left">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-600" />
            <span>{error}</span>
          </div>
        )}

        {!isPrerequisiteReady ? (
          <div className="max-w-md mx-auto mb-2 p-3 rounded-xl bg-slate-100/90 border border-slate-200 text-slate-600 text-xs flex items-center gap-2 justify-center">
            <Clock className="w-4 h-4 text-slate-500" />
            <span>Waiting for repository code parsing and CallGraph completion</span>
          </div>
        ) : !readOnly && (
          <button
            onClick={() => onGenerate && onGenerate(false)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 text-white font-medium text-sm shadow-sm transition transform active:scale-95"
          >
            <Workflow className="w-4 h-4" />
            <span>Discover Application Workflows</span>
          </button>
        )}
      </div>
    );
  }

  // 2. Loading state
  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-violet-200 p-8 shadow-sm mb-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-violet-100 text-violet-600 flex items-center justify-center mx-auto mb-4 animate-spin">
          <Workflow className="w-6 h-6" />
        </div>
        <h3 className="text-base font-bold text-slate-900 mb-1">
          Analyzing Application Workflows & Data Flows...
        </h3>
        <p className="text-xs text-slate-500 max-w-md mx-auto">
          Traversing static CallGraph edges, verifying AST control-flow reachability,
          and constructing end-to-end execution paths with grounded evidence.
        </p>
      </div>
    );
  }

  if (!workflowUnderstanding) return null;

  const workflows = workflowUnderstanding.workflows || [];
  const structuralChains = workflowUnderstanding.structural_call_chains || [];
  const omittedCandidates = workflowUnderstanding.omitted_candidate_workflows || [];
  const tokenUsage = workflowUnderstanding.token_usage;
  const currentWorkflow = workflows[selectedWorkflowIdx] || workflows[0] || null;

  // Flatten all data flows and operations across workflows for dedicated tabs
  const allDataFlows = workflows.flatMap((w) => w.data_flows || []);
  const allSteps = workflows.flatMap((w) => w.steps || []);

  // Filtered storage & API operations
  const storageOps = allDataFlows.filter((df) => df.storage_library_detected || df.storage_operation_verified);
  const externalApiOps = allDataFlows.filter((df) => df.external_api_library_detected || df.external_api_operation_verified);

  return (
    <div className="bg-white rounded-2xl border border-violet-200 shadow-sm p-6 sm:p-8 mb-6 relative overflow-hidden">
      {/* Top Header & Metadata */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 mb-5 border-b border-slate-100">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <div className="px-2.5 py-1 rounded-md bg-violet-100 text-violet-800 text-xs font-bold flex items-center gap-1.5">
              <Workflow className="w-3.5 h-3.5 text-violet-600" />
              <span>Milestone 3.4 & 3.5 • Application Workflow Understanding</span>
            </div>

            {workflowUnderstanding.is_fallback ? (
              <span className="px-2.5 py-1 rounded-md bg-amber-100 text-amber-800 text-xs font-semibold flex items-center gap-1 border border-amber-200">
                <ShieldCheck className="w-3.5 h-3.5 text-amber-600" />
                <span>Deterministic Fallback (Offline Mode)</span>
              </span>
            ) : (
              <span className="px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 text-xs font-semibold flex items-center gap-1 border border-emerald-200">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                <span>AI Grounded Analysis ({workflowUnderstanding.provider || 'Provider'}/{workflowUnderstanding.model || 'Model'})</span>
              </span>
            )}

            <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 text-xs font-mono font-medium border border-slate-200">
              {workflowUnderstanding.system_architecture_type || 'Modular Architecture'}
            </span>
          </div>

          <h3 className="text-xl font-bold text-slate-900 tracking-tight">
            {workflowUnderstanding.repository_name} — Execution Paths & Data Flow
          </h3>
        </div>

        {/* Action Controls & Latency */}
        <div className="flex items-center gap-3 self-start sm:self-center flex-wrap">
          <div className="text-right text-xs text-slate-500 hidden sm:block">
            <div className="flex items-center gap-1 text-slate-600 justify-end">
              <Clock className="w-3 h-3 text-slate-400" />
              <span>{Math.round(workflowUnderstanding.latency_ms)} ms</span>
            </div>
            {tokenUsage && (
              <div className="text-[11px] text-slate-400">
                {tokenUsage.total_tokens?.toLocaleString()} tokens ({tokenUsage.prompt_tokens} in / {tokenUsage.completion_tokens} out)
              </div>
            )}
          </div>

          {!readOnly && (
            <button
              onClick={() => onGenerate && onGenerate(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:text-violet-700 hover:bg-violet-50 hover:border-violet-300 text-xs font-medium transition"
              title="Regenerate Workflow Understanding (Force Refresh)"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Regenerate</span>
            </button>
          )}
        </div>
      </div>

      {/* Fallback Notice Banner */}
      {workflowUnderstanding.is_fallback && (
        <div className="mb-5 p-3.5 rounded-xl bg-amber-50/80 border border-amber-200 text-amber-900 text-xs leading-relaxed flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-bold">Deterministic Fallback Mode:</span> Workflows below were reconstructed
            deterministically from static CallGraph reachability and AST statement orders.
            No live external LLM provider was contacted.
          </div>
        </div>
      )}

      {/* Static Analysis Caveat Banner */}
      <div className="mb-5 p-3 rounded-xl bg-slate-50 border border-slate-200/80 text-slate-600 text-xs flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Info className="w-4 h-4 text-indigo-500 flex-shrink-0" />
          <span>
            <strong>Static Analysis Notice:</strong> Execution paths and data flows are established statically
            from AST call expressions. Runtime execution is never executed or profiled.
          </span>
        </div>
        <span className="text-[11px] text-slate-400 font-mono hidden md:inline">AST Verified</span>
      </div>

      {/* Section A: Overview Summary Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
            <Workflow className="w-3.5 h-3.5 text-violet-600" />
            <span>AI Workflows</span>
          </div>
          <p className="text-xl font-bold text-slate-900 font-mono">{workflows.length}</p>
        </div>

        <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
            <Network className="w-3.5 h-3.5 text-indigo-600" />
            <span>Structural Chains</span>
          </div>
          <p className="text-xl font-bold text-slate-900 font-mono">{structuralChains.length}</p>
        </div>

        <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
            <Database className="w-3.5 h-3.5 text-amber-600" />
            <span>Storage & API Ops</span>
          </div>
          <p className="text-xl font-bold text-slate-900 font-mono">{storageOps.length + externalApiOps.length}</p>
        </div>

        <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
            <HelpCircle className="w-3.5 h-3.5 text-slate-500" />
            <span>Omitted Candidates</span>
          </div>
          <p className="text-xl font-bold text-slate-900 font-mono">{omittedCandidates.length}</p>
        </div>
      </div>

      {/* High-level workflow summary text */}
      {workflowUnderstanding.workflow_summary && (
        <div className="p-4 rounded-xl bg-violet-50/50 border border-violet-100 text-xs sm:text-sm text-slate-700 leading-relaxed mb-6">
          <span className="font-bold text-violet-900 mr-1.5">Architecture Summary:</span>
          {workflowUnderstanding.workflow_summary}
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200 pb-3 mb-6 overflow-x-auto text-xs font-semibold">
        <button
          onClick={() => setActiveTab('workflows')}
          className={`px-3 py-1.5 rounded-lg transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'workflows'
              ? 'bg-violet-600 text-white shadow-sm'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
        >
          <Workflow className="w-3.5 h-3.5" />
          <span>Application Workflows ({workflows.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('data_flows')}
          className={`px-3 py-1.5 rounded-lg transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'data_flows'
              ? 'bg-violet-600 text-white shadow-sm'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
        >
          <Share2 className="w-3.5 h-3.5" />
          <span>Data Flows ({allDataFlows.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('operations')}
          className={`px-3 py-1.5 rounded-lg transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'operations'
              ? 'bg-violet-600 text-white shadow-sm'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
        >
          <Database className="w-3.5 h-3.5" />
          <span>Storage & API Operations ({storageOps.length + externalApiOps.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('structural_chains')}
          className={`px-3 py-1.5 rounded-lg transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'structural_chains'
              ? 'bg-violet-600 text-white shadow-sm'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
        >
          <Network className="w-3.5 h-3.5" />
          <span>Structural Chains ({structuralChains.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('evidence_limitations')}
          className={`px-3 py-1.5 rounded-lg transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'evidence_limitations'
              ? 'bg-violet-600 text-white shadow-sm'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
        >
          <ShieldCheck className="w-3.5 h-3.5" />
          <span>Evidence & Limitations</span>
        </button>
      </div>

      {/* =========================================================================
          TAB 1: APPLICATION WORKFLOWS & STEP-BY-STEP VERTICAL FLOW
         ========================================================================= */}
      {activeTab === 'workflows' && (
        <div>
          {workflows.length === 0 ? (
            <div className="p-8 text-center bg-slate-50 rounded-xl border border-slate-200">
              <Workflow className="w-8 h-8 text-slate-400 mx-auto mb-2" />
              <h4 className="text-sm font-bold text-slate-800">No Semantic Workflows Discovered</h4>
              <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 mb-4">
                Static discovery found no multi-step call chains meeting candidate thresholds.
                Deterministic structural call chains may be inspected in the Structural Chains tab.
              </p>
              {structuralChains.length > 0 && (
                <button
                  onClick={() => setActiveTab('structural_chains')}
                  className="px-3.5 py-1.5 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-700 text-xs font-semibold hover:bg-indigo-100 transition"
                >
                  View Deterministic Structural Chains ({structuralChains.length})
                </button>
              )}
            </div>
          ) : (
            <div>
              {/* Workflow Selector (if multiple workflows) */}
              {workflows.length > 1 && (
                <div className="flex items-center gap-2 mb-5 overflow-x-auto pb-1">
                  {workflows.map((wf, idx) => (
                    <button
                      key={wf.workflow_id || idx}
                      onClick={() => {
                        setSelectedWorkflowIdx(idx);
                        setExpandedStepIdx(null);
                      }}
                      className={`px-3 py-2 rounded-xl text-xs font-medium border text-left transition flex-shrink-0 flex items-center gap-2 ${
                        selectedWorkflowIdx === idx
                          ? 'border-violet-600 bg-violet-50 text-violet-900 font-bold shadow-sm'
                          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <span className="w-5 h-5 rounded-full bg-violet-200 text-violet-800 flex items-center justify-center text-[10px] font-bold">
                        {idx + 1}
                      </span>
                      <span className="truncate max-w-[200px]">{wf.name}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-mono">
                        {wf.steps?.length || 0} steps
                      </span>
                    </button>
                  ))}
                </div>
              )}

              {currentWorkflow && (
                <div className="space-y-6">
                  {/* Workflow Card Header */}
                  <div className="p-4 sm:p-5 rounded-2xl bg-gradient-to-r from-violet-50/70 to-indigo-50/40 border border-violet-100">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="px-2.5 py-0.5 rounded-full bg-violet-600 text-white text-xs font-bold uppercase tracking-wider">
                          {currentWorkflow.category || 'Workflow'}
                        </span>
                        <h4 className="text-base sm:text-lg font-bold text-slate-900">
                          {currentWorkflow.name}
                        </h4>
                      </div>
                      <span className="text-xs font-mono text-slate-500">
                        Confidence: <strong className="text-slate-800 uppercase">{currentWorkflow.confidence || 'high'}</strong>
                      </span>
                    </div>

                    <p className="text-xs sm:text-sm text-slate-700 leading-relaxed mb-4">
                      {currentWorkflow.description}
                    </p>

                    {/* Trigger and Outcome */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                      <div className="p-2.5 rounded-xl bg-white/80 border border-violet-100">
                        <span className="font-bold text-violet-900 block mb-0.5">Execution Trigger:</span>
                        <span className="text-slate-600">{currentWorkflow.trigger}</span>
                      </div>
                      <div className="p-2.5 rounded-xl bg-white/80 border border-violet-100">
                        <span className="font-bold text-violet-900 block mb-0.5">Final Outcome:</span>
                        <span className="text-slate-600">{currentWorkflow.final_outcome}</span>
                      </div>
                    </div>

                    {/* Entry Point & Participating Components */}
                    <div className="mt-4 pt-3 border-t border-violet-200/60 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-slate-500 font-semibold">Entry Point:</span>
                        <span className="px-2 py-0.5 rounded bg-violet-100 text-violet-800 font-mono font-medium">
                          {currentWorkflow.entry_point?.name || 'Entry'} ({sanitizePath(currentWorkflow.entry_point?.component_id)})
                        </span>
                        {currentWorkflow.entry_point?.role_in_workflow && (
                          <span className="text-slate-500 text-[11px]">
                            — {currentWorkflow.entry_point.role_in_workflow}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Participating Components Chips */}
                    {currentWorkflow.participating_components && currentWorkflow.participating_components.length > 0 && (
                      <div className="mt-3 flex items-center gap-2 flex-wrap text-xs">
                        <span className="text-slate-500 font-semibold">Participating Components:</span>
                        {currentWorkflow.participating_components.map((comp, cIdx) => (
                          <span
                            key={comp.component_id || cIdx}
                            className="px-2 py-0.5 rounded-md bg-white border border-slate-200 text-slate-700 font-mono text-[11px]"
                            title={`${comp.name}: ${comp.role_in_workflow}`}
                          >
                            {comp.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Multi-Dimensional Verification Status Matrix */}
                  <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80">
                    <h5 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-2.5 flex items-center gap-1.5">
                      <ShieldCheck className="w-3.5 h-3.5 text-violet-600" />
                      <span>Static Verification Dimensions</span>
                    </h5>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                      <div className="p-2 rounded-lg bg-white border border-slate-200 flex items-center justify-between">
                        <span className="text-slate-600">Call Graph Edges:</span>
                        {currentWorkflow.call_relationships_fully_verified ? (
                          <span className="inline-flex items-center gap-1 font-bold text-emerald-700">
                            <Check className="w-3 h-3 text-emerald-600" /> Verified
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 font-medium text-slate-500">
                            Partial
                          </span>
                        )}
                      </div>

                      <div className="p-2 rounded-lg bg-white border border-slate-200 flex items-center justify-between">
                        <span className="text-slate-600">Source Order:</span>
                        {currentWorkflow.source_order_verified ? (
                          <span className="inline-flex items-center gap-1 font-bold text-emerald-700">
                            <Check className="w-3 h-3 text-emerald-600" /> Verified
                          </span>
                        ) : (
                          <span className="text-slate-500 font-medium">Unordered</span>
                        )}
                      </div>

                      <div className="p-2 rounded-lg bg-white border border-slate-200 flex items-center justify-between">
                        <span className="text-slate-600">Shared Execution Path:</span>
                        {currentWorkflow.same_execution_path_verified ? (
                          <span className="inline-flex items-center gap-1 font-bold text-emerald-700">
                            <Check className="w-3 h-3 text-emerald-600" /> Established
                          </span>
                        ) : (
                          <span className="text-amber-700 font-medium">Disjoint / Branch</span>
                        )}
                      </div>

                      <div className="p-2 rounded-lg bg-white border border-slate-200 flex items-center justify-between" title="Static guarantee along normal non-exceptional control-flow path">
                        <span className="text-slate-600">Normal Path Guaranteed:</span>
                        {currentWorkflow.execution_guaranteed ? (
                          <span className="inline-flex items-center gap-1 font-bold text-emerald-700">
                            <Check className="w-3 h-3 text-emerald-600" /> Guaranteed
                          </span>
                        ) : (
                          <span className="text-slate-500 font-medium">Possible Only</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Section C: Workflow Steps (Ordered Sequence Visualization) */}
                  <div>
                    <h5 className="text-sm font-bold text-slate-900 mb-3 flex items-center gap-2">
                      <Layers className="w-4 h-4 text-violet-600" />
                      <span>Ordered Workflow Steps ({currentWorkflow.steps?.length || 0})</span>
                    </h5>

                    <div className="relative pl-6 space-y-4 before:content-[''] before:absolute before:left-2.5 before:top-3 before:bottom-3 before:w-0.5 before:bg-violet-200">
                      {currentWorkflow.steps?.map((step, sIdx) => {
                        const isExpanded = expandedStepIdx === sIdx;
                        const callEv = step.call_evidence;

                        // Action type badge formatting
                        const actionColors = {
                          entry: 'bg-blue-50 text-blue-700 border-blue-200',
                          call: 'bg-violet-50 text-violet-700 border-violet-200',
                          transformation: 'bg-indigo-50 text-indigo-700 border-indigo-200',
                          storage_io: 'bg-amber-50 text-amber-700 border-amber-200',
                          external_api: 'bg-emerald-50 text-emerald-700 border-emerald-200',
                          response: 'bg-slate-50 text-slate-700 border-slate-200',
                        };

                        return (
                          <div
                            key={step.step_number || sIdx}
                            className="relative bg-white rounded-xl border border-slate-200 p-4 shadow-sm hover:border-violet-300 transition"
                          >
                            {/* Step Node Dot */}
                            <div className="absolute -left-[27px] top-4 w-5 h-5 rounded-full bg-violet-600 text-white font-bold text-[10px] flex items-center justify-center ring-4 ring-white shadow-sm">
                              {step.step_number}
                            </div>

                            {/* Step Header */}
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 mb-2 border-b border-slate-100">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-bold text-slate-900">{step.title}</span>
                                <span className={`px-2 py-0.5 rounded text-[11px] font-semibold border ${actionColors[step.action_type] || actionColors.call}`}>
                                  {step.action_type}
                                </span>
                                {step.symbol_name && (
                                  <span className="font-mono text-xs font-semibold text-violet-700 bg-violet-50 px-2 py-0.5 rounded">
                                    {step.symbol_name}
                                  </span>
                                )}
                              </div>

                              <div className="flex items-center gap-2 text-xs">
                                <span className="text-slate-400 font-mono text-[11px]">
                                  Component: {sanitizePath(step.component_id)}
                                </span>
                              </div>
                            </div>

                            {/* Step Description */}
                            <p className="text-xs sm:text-sm text-slate-700 leading-relaxed mb-3">
                              {step.description}
                            </p>

                            {/* Verification Badges Row */}
                            <div className="flex items-center gap-2 flex-wrap mb-3 text-[11px]">
                              {step.call_relationship_verified ? (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium">
                                  <Check className="w-3 h-3 text-emerald-600" /> Edge Verified
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-50 text-slate-500 border border-slate-200">
                                  Edge Unverified
                                </span>
                              )}

                              {step.source_order_verified && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium">
                                  <Check className="w-3 h-3 text-emerald-600" /> Source Order Verified
                                </span>
                              )}

                              {step.same_execution_path_verified && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium">
                                  <Check className="w-3 h-3 text-emerald-600" /> Same Execution Path
                                </span>
                              )}

                              {step.execution_guaranteed ? (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium" title="Guaranteed along normal path (AST analysis excludes dynamic callee exceptions)">
                                  <Check className="w-3 h-3 text-emerald-600" /> Normal Path Guaranteed
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-50 text-slate-500 border border-slate-200">
                                  Conditional / Branching
                                </span>
                              )}

                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 text-slate-500 font-mono text-[10px]">
                                Runtime Not Run
                              </span>
                            </div>

                            {/* Data Flow across steps */}
                            {(step.data_received || step.data_produced) && (
                              <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200/60 text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 mb-2">
                                {step.data_received && (
                                  <div className="flex items-center gap-1.5 text-slate-600">
                                    <span className="font-semibold text-slate-700">In:</span>
                                    <span className="font-mono text-slate-800 bg-white px-1.5 py-0.5 rounded border border-slate-200 text-[11px]">
                                      {step.data_received}
                                    </span>
                                  </div>
                                )}
                                {step.data_produced && (
                                  <div className="flex items-center gap-1.5 text-slate-600">
                                    <span className="font-semibold text-slate-700">Out:</span>
                                    <span className="font-mono text-slate-800 bg-white px-1.5 py-0.5 rounded border border-slate-200 text-[11px]">
                                      {step.data_produced}
                                    </span>
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Call Evidence Toggle & Details */}
                            {callEv && (
                              <div className="mt-2 pt-2 border-t border-slate-100">
                                <button
                                  onClick={() => setExpandedStepIdx(isExpanded ? null : sIdx)}
                                  className="text-xs text-violet-600 hover:text-violet-800 font-medium flex items-center gap-1 transition"
                                >
                                  {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                                  <span>{isExpanded ? 'Hide Call Site Evidence' : 'Show Source Call Site Evidence'}</span>
                                </button>

                                {isExpanded && (
                                  <div className="mt-2 p-3 rounded-lg bg-slate-900 text-slate-200 font-mono text-[11px] space-y-1 overflow-x-auto">
                                    <div>
                                      <span className="text-violet-400">Caller:</span> {sanitizePath(callEv.caller_file)} : {callEv.caller_symbol}
                                    </div>
                                    <div>
                                      <span className="text-emerald-400">Callee:</span> {sanitizePath(callEv.callee_file)} : {callEv.callee_symbol}
                                    </div>
                                    <div>
                                      <span className="text-amber-400">Call Expression:</span> {callEv.call_name}() at line {callEv.call_site_line}
                                      {callEv.call_site_column ? ` (col ${callEv.call_site_column})` : ''}
                                    </div>
                                    <div className="text-slate-400 text-[10px] pt-1 border-t border-slate-800">
                                      CallSite ID: {callEv.call_site_id}
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* =========================================================================
          TAB 2: DATA FLOWS (ORIGIN -> DESTINATION & TRANSFORMATIONS)
         ========================================================================= */}
      {activeTab === 'data_flows' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-100">
            <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2">
              <Share2 className="w-4 h-4 text-violet-600" />
              <span>Grounded Data Flows ({allDataFlows.length})</span>
            </h4>
            <span className="text-xs text-slate-500">
              Traces data objects, lifecycle stages, and verifiable AST transformations
            </span>
          </div>

          {allDataFlows.length === 0 ? (
            <div className="p-8 text-center bg-slate-50 rounded-xl border border-slate-200">
              <Share2 className="w-8 h-8 text-slate-400 mx-auto mb-2" />
              <p className="text-xs text-slate-600">No discrete data flow records observed in discovered workflows.</p>
            </div>
          ) : (
            allDataFlows.map((df, dfIdx) => {
              // Status formatting
              const isObserved = df.data_relationship_status === 'observed';
              const isInferred = df.data_relationship_status === 'inferred';

              return (
                <div key={df.flow_id || dfIdx} className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm space-y-3">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-slate-900 text-sm">{df.data_item_name}</span>
                      {isObserved ? (
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1">
                          <Check className="w-3 h-3 text-emerald-600" /> Observed in AST
                        </span>
                      ) : isInferred ? (
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-600 border border-slate-200">
                          Inferred Data Relation
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                          Unresolved
                        </span>
                      )}
                    </div>
                    <span className="text-xs font-mono text-slate-400">Flow ID: {df.flow_id}</span>
                  </div>

                  {/* Origin to Destination */}
                  <div className="p-3 rounded-lg bg-slate-50 border border-slate-200/80 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
                    <div className="w-full sm:w-auto">
                      <span className="text-slate-400 text-[10px] block uppercase font-bold">Origin Component</span>
                      <span className="font-semibold text-slate-800">{df.origin?.name}</span>
                      <span className="text-slate-500 block font-mono text-[11px]">{sanitizePath(df.origin?.component_id)}</span>
                    </div>

                    <ArrowRight className="w-4 h-4 text-violet-500 hidden sm:block flex-shrink-0" />
                    <ArrowDown className="w-4 h-4 text-violet-500 sm:hidden flex-shrink-0 my-1" />

                    <div className="w-full sm:w-auto text-left sm:text-right">
                      <span className="text-slate-400 text-[10px] block uppercase font-bold">Destination Component</span>
                      <span className="font-semibold text-slate-800">{df.destination?.name}</span>
                      <span className="text-slate-500 block font-mono text-[11px]">{sanitizePath(df.destination?.component_id)}</span>
                    </div>
                  </div>

                  {/* Lifecycle stages */}
                  {df.lifecycle_stages && df.lifecycle_stages.length > 0 && (
                    <div className="flex items-center gap-1.5 flex-wrap text-xs">
                      <span className="text-slate-500 font-semibold">Lifecycle:</span>
                      {df.lifecycle_stages.map((stage, stIdx) => (
                        <span key={stIdx} className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 text-[11px] font-mono">
                          {stage}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Concrete Data Transformations */}
                  {df.transformations && df.transformations.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-slate-100 space-y-2">
                      <span className="text-xs font-bold text-slate-700 block">AST Data Transformations:</span>
                      {df.transformations.map((tx, txIdx) => (
                        <div key={txIdx} className="p-3 rounded-lg bg-violet-50/40 border border-violet-100 text-xs space-y-1.5">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-semibold text-violet-900">{tx.transformation_name}</span>
                            {tx.transformation_verified ? (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800">
                                Verified Transformation
                              </span>
                            ) : (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600">
                                Inferred
                              </span>
                            )}
                          </div>
                          <div className="text-slate-600">{tx.transformation_logic}</div>
                          <div className="flex items-center gap-2 font-mono text-[11px] text-slate-500">
                            <span>{tx.input_format_or_type}</span>
                            <ArrowRight className="w-3 h-3 text-violet-500" />
                            <span>{tx.output_format_or_type}</span>
                          </div>
                          {tx.observed_operation && (
                            <div className="text-[11px] font-mono text-indigo-700 bg-white/70 px-2 py-1 rounded border border-indigo-100">
                              Observed: {tx.observed_operation}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}

      {/* =========================================================================
          TAB 3: STORAGE AND EXTERNAL API OPERATIONS
         ========================================================================= */}
      {activeTab === 'operations' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-slate-100">
            <div>
              <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <Database className="w-4 h-4 text-violet-600" />
                <span>Storage & External API Operations</span>
              </h4>
              <p className="text-xs text-slate-500 mt-0.5">
                Classification of static database read/write/delete calls and outgoing HTTP/SDK operations.
              </p>
            </div>

            {/* Sub-filter */}
            <div className="flex items-center gap-1.5 text-xs">
              {['all', 'storage', 'external_api'].map((f) => (
                <button
                  key={f}
                  onClick={() => setOperationFilter(f)}
                  className={`px-2.5 py-1 rounded-md capitalize transition ${
                    operationFilter === f
                      ? 'bg-slate-800 text-white font-semibold'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {f === 'all' ? 'All Operations' : f === 'storage' ? 'Database & Storage' : 'External APIs'}
                </button>
              ))}
            </div>
          </div>

          {storageOps.length === 0 && externalApiOps.length === 0 ? (
            <div className="p-8 text-center bg-slate-50 rounded-xl border border-slate-200">
              <Database className="w-8 h-8 text-slate-400 mx-auto mb-2" />
              <p className="text-xs text-slate-600">No database or external API operations detected in the analyzed workflows.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Storage Operations */}
              {(operationFilter === 'all' || operationFilter === 'storage') && storageOps.map((op, oIdx) => (
                <div key={`st-${oIdx}`} className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm space-y-2">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 text-xs font-bold uppercase tracking-wider">
                        {op.storage_operation_type ? `DB ${op.storage_operation_type.toUpperCase()}` : 'Storage IO'}
                      </span>
                      <span className="font-bold text-slate-900 text-sm">
                        {op.data_item_name}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5 text-xs">
                      {op.storage_operation_verified ? (
                        <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold flex items-center gap-1">
                          <Check className="w-3 h-3 text-emerald-600" /> Static Operation Verified
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200">
                          Library Detected Only
                        </span>
                      )}
                    </div>
                  </div>

                  <p className="text-xs text-slate-600">
                    <strong className="text-slate-700">Classification: </strong>
                    {op.persistence_status}
                  </p>

                  {op.persistence_detail && (
                    <div className="p-2.5 rounded-lg bg-amber-50/60 border border-amber-200/80 font-mono text-[11px] text-amber-900">
                      {op.persistence_detail}
                    </div>
                  )}

                  <div className="text-[11px] text-slate-500 font-mono">
                    Component: {sanitizePath(op.destination?.component_id || op.origin?.component_id)}
                  </div>
                </div>
              ))}

              {/* External API Operations */}
              {(operationFilter === 'all' || operationFilter === 'external_api') && externalApiOps.map((api, aIdx) => (
                <div key={`api-${aIdx}`} className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm space-y-2">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 text-xs font-bold uppercase tracking-wider">
                        {api.external_api_operation_type ? api.external_api_operation_type.toUpperCase() : 'HTTP CALL'}
                      </span>
                      <span className="font-bold text-slate-900 text-sm">
                        {api.data_item_name}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5 text-xs">
                      {api.external_api_operation_verified ? (
                        <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold flex items-center gap-1">
                          <Check className="w-3 h-3 text-emerald-600" /> Static HTTP Call Verified
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200">
                          Library Detected Only
                        </span>
                      )}
                    </div>
                  </div>

                  <p className="text-xs text-slate-600">
                    <strong className="text-slate-700">Classification: </strong>
                    {api.external_api_status}
                  </p>

                  {api.external_api_detail && (
                    <div className="p-2.5 rounded-lg bg-emerald-50/60 border border-emerald-200/80 font-mono text-[11px] text-emerald-900">
                      {api.external_api_detail}
                    </div>
                  )}

                  <div className="text-[11px] text-slate-500 font-mono">
                    Component: {sanitizePath(api.origin?.component_id)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* =========================================================================
          TAB 4: DETERMINISTIC STRUCTURAL CALL CHAINS (SEPARATE PROVENANCE)
         ========================================================================= */}
      {activeTab === 'structural_chains' && (
        <div className="space-y-4">
          <div className="p-3.5 rounded-xl bg-indigo-50/70 border border-indigo-200 text-xs text-indigo-900 leading-relaxed">
            <span className="font-bold block mb-1">Deterministic Provenance:</span>
            Structural call chains are reconstructed deterministically from static CallGraph reachability.
            They are presented separately from semantic AI workflows to clearly distinguish deterministic AST evidence from LLM interpretations.
          </div>

          {structuralChains.length === 0 ? (
            <div className="p-8 text-center bg-slate-50 rounded-xl border border-slate-200">
              <Network className="w-8 h-8 text-slate-400 mx-auto mb-2" />
              <p className="text-xs text-slate-600">No standalone structural chains reported.</p>
            </div>
          ) : (
            structuralChains.map((chain, cIdx) => (
              <div key={chain.chain_id || cIdx} className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-slate-100">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 text-xs font-mono font-bold">
                        Chain #{cIdx + 1}
                      </span>
                      <span className="font-mono text-xs font-bold text-indigo-700">
                        {chain.entry_symbol}
                      </span>
                    </div>
                    <span className="text-[11px] font-mono text-slate-400 block mt-0.5">
                      Entry: {sanitizePath(chain.entry_file)}
                    </span>
                  </div>

                  <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-600">
                    {chain.steps?.length || 0} transitions
                  </span>
                </div>

                <div className="text-xs text-slate-600 italic">
                  Reason: {chain.unresolved_reason}
                </div>

                {/* Steps in structural chain */}
                <div className="space-y-2 pt-1">
                  {chain.steps?.map((step, stIdx) => (
                    <div key={stIdx} className="p-2.5 rounded-lg bg-slate-50 border border-slate-200/60 text-xs flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-slate-200 text-slate-700 text-[10px] font-bold flex items-center justify-center">
                          {stIdx + 1}
                        </span>
                        <span className="font-semibold text-slate-800">{step.title}</span>
                        {step.symbol_name && (
                          <span className="font-mono text-violet-700 bg-violet-50 px-1.5 py-0.5 rounded text-[11px]">
                            {step.symbol_name}
                          </span>
                        )}
                      </div>
                      <span className="font-mono text-[11px] text-slate-400">
                        {sanitizePath(step.component_id)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* =========================================================================
          TAB 5: EVIDENCE, WARNINGS & LIMITATIONS
         ========================================================================= */}
      {activeTab === 'evidence_limitations' && (
        <div className="space-y-5">
          {/* Validation Warnings */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-2 flex items-center gap-1.5">
              <AlertCircle className="w-3.5 h-3.5 text-amber-600" />
              <span>Validation Warnings ({workflowUnderstanding.validation_warnings?.length || 0})</span>
            </h4>
            {workflowUnderstanding.validation_warnings && workflowUnderstanding.validation_warnings.length > 0 ? (
              <div className="p-3 rounded-xl bg-amber-50/70 border border-amber-200 text-amber-900 text-xs space-y-1.5">
                {workflowUnderstanding.validation_warnings.map((w, wIdx) => (
                  <div key={wIdx} className="flex items-start gap-2">
                    <span className="text-amber-600 font-bold">•</span>
                    <span>{sanitizePath(w)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">No validation warnings encountered.</p>
            )}
          </div>

          {/* Omitted Candidate Workflows */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-2 flex items-center gap-1.5">
              <Boxes className="w-3.5 h-3.5 text-slate-500" />
              <span>Omitted Candidate Workflows ({omittedCandidates.length})</span>
            </h4>
            {omittedCandidates.length > 0 ? (
              <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 text-xs space-y-1.5">
                {omittedCandidates.map((om, omIdx) => (
                  <div key={omIdx} className="flex items-start gap-2 text-slate-600">
                    <span className="text-slate-400 font-bold">•</span>
                    <span>{sanitizePath(om)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">All discovered candidates met inclusion criteria.</p>
            )}
          </div>

          {/* Analysis Limitations & Static Caveats */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-2 flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-indigo-600" />
              <span>Static Analysis Caveats & Scope</span>
            </h4>
            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-600 space-y-2 leading-relaxed">
              {(workflowUnderstanding.static_analysis_caveats || []).map((cav, cIdx) => (
                <div key={cIdx} className="flex items-start gap-2">
                  <Check className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0 mt-0.5" />
                  <span>{cav}</span>
                </div>
              ))}
              {(workflowUnderstanding.analysis_limitations || []).map((lim, lIdx) => (
                <div key={`lim-${lIdx}`} className="flex items-start gap-2 text-slate-500">
                  <Info className="w-3.5 h-3.5 text-indigo-500 flex-shrink-0 mt-0.5" />
                  <span>{sanitizePath(lim)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
