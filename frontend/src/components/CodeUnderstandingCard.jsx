import React, { useState } from 'react';
import {
  Code2,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  Layers,
  ArrowRight,
  RefreshCw,
  Cpu,
  Clock,
  ShieldCheck,
  Zap,
  ChevronDown,
  ChevronUp,
  FileCode,
  Network,
  Binary,
  GitCommit,
  ExternalLink,
} from 'lucide-react';

export default function CodeUnderstandingCard({
  codeUnderstanding,
  isLoading,
  onGenerate,
  error,
}) {
  const [activeTab, setActiveTab] = useState('components'); // 'components' | 'logic' | 'interactions' | 'architecture'
  const [selectedComponentIdx, setSelectedComponentIdx] = useState(0);
  const [expandedCodeIdx, setExpandedCodeIdx] = useState(null);

  // If not yet generated and not loading
  if (!codeUnderstanding && !isLoading) {
    return (
      <div className="bg-gradient-to-br from-purple-50/60 via-white to-indigo-50/40 rounded-2xl border border-purple-200 p-6 sm:p-8 shadow-sm mb-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-purple-600 text-white flex items-center justify-center mx-auto mb-4 shadow-md shadow-purple-200">
          <Code2 className="w-6 h-6" />
        </div>
        <h3 className="text-lg font-bold text-slate-900 mb-2">
          Component & Code-Level Understanding Ready
        </h3>
        <p className="text-sm text-slate-600 max-w-xl mx-auto mb-6 leading-relaxed">
          RepoGenie can deeply analyze the repository's primary architectural components,
          explain the internal logic of key functions and classes, and map component interactions
          grounded in source code evidence.
        </p>

        {error && (
          <div className="max-w-md mx-auto mb-5 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2 text-left">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-600" />
            <span>{error}</span>
          </div>
        )}

        <button
          onClick={() => onGenerate && onGenerate(false)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-medium text-sm shadow-sm transition transform active:scale-95"
        >
          <Code2 className="w-4 h-4" />
          <span>Analyze Component & Code Logic</span>
        </button>
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-purple-200 p-8 shadow-sm mb-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-purple-100 text-purple-600 flex items-center justify-center mx-auto mb-4 animate-spin">
          <Code2 className="w-6 h-6" />
        </div>
        <h3 className="text-base font-bold text-slate-900 mb-1">
          Generating Component & Code Understanding...
        </h3>
        <p className="text-xs text-slate-500 max-w-md mx-auto">
          Selecting central architectural components, extracting complete AST snippets,
          and reasoning over code logic and component interactions.
        </p>
      </div>
    );
  }

  if (!codeUnderstanding) return null;

  const components = codeUnderstanding.components || [];
  const interactions = codeUnderstanding.cross_component_interactions || [];
  const tokenUsage = codeUnderstanding.token_usage;
  const currentComponent = components[selectedComponentIdx] || components[0] || {};

  return (
    <div className="bg-white rounded-2xl border border-purple-200 shadow-sm p-6 sm:p-8 mb-6 relative overflow-hidden">
      {/* Top Header & AI Metadata */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 mb-5 border-b border-slate-100">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <div className="px-2.5 py-1 rounded-md bg-purple-100 text-purple-800 text-xs font-bold flex items-center gap-1.5">
              <Code2 className="w-3.5 h-3.5 text-purple-600" />
              <span>Milestone 3.3 • Code-Level Understanding</span>
            </div>

            {codeUnderstanding.is_fallback ? (
              <span className="px-2.5 py-1 rounded-md bg-amber-100 text-amber-800 text-xs font-semibold flex items-center gap-1 border border-amber-200">
                <ShieldCheck className="w-3.5 h-3.5 text-amber-600" />
                <span>Deterministic Fallback (Offline Mode)</span>
              </span>
            ) : (
              <span className="px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 text-xs font-semibold flex items-center gap-1 border border-emerald-200">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                <span>AI Grounded Analysis ({codeUnderstanding.provider}/{codeUnderstanding.model})</span>
              </span>
            )}
          </div>
          <h3 className="text-xl font-bold text-slate-900">
            {codeUnderstanding.repository_name} — Architectural & Code Logic
          </h3>
        </div>

        {/* Action Controls & Latency */}
        <div className="flex items-center gap-3 self-start sm:self-center flex-wrap">
          <div className="text-right text-xs text-slate-500 hidden sm:block">
            <div className="flex items-center gap-1 text-slate-600">
              <Clock className="w-3 h-3 text-slate-400" />
              <span>{codeUnderstanding.latency_ms} ms</span>
            </div>
            {tokenUsage && (
              <div className="text-[11px] text-slate-400">
                {tokenUsage.total_tokens?.toLocaleString()} tokens ({tokenUsage.prompt_tokens} in / {tokenUsage.completion_tokens} out)
              </div>
            )}
          </div>

          <button
            onClick={() => onGenerate && onGenerate(true)}
            className="p-2 rounded-xl border border-slate-200 hover:border-purple-300 hover:bg-purple-50 text-slate-600 hover:text-purple-700 transition"
            title="Re-run Code Understanding"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Fallback Notice Banner */}
      {codeUnderstanding.is_fallback && (
        <div className="mb-5 p-3.5 rounded-xl bg-amber-50/80 border border-amber-200 text-amber-900 text-xs leading-relaxed flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-bold">Offline Static Mode:</span> Explanations below were derived
            deterministically from Tree-sitter AST signatures, docstrings, and static dependency graphs.
            Internal algorithmic execution branches were not evaluated by an external LLM provider.
          </div>
        </div>
      )}

      {/* Validation Warnings Callout */}
      {codeUnderstanding.validation_warnings && codeUnderstanding.validation_warnings.length > 0 && (
        <div className="mb-5 p-3 rounded-xl bg-slate-50 border border-slate-200 text-slate-700 text-xs space-y-1">
          <div className="font-semibold text-slate-800 flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-purple-600" />
            <span>Static Validation Notes ({codeUnderstanding.validation_warnings.length}):</span>
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-slate-600">
            {codeUnderstanding.validation_warnings.slice(0, 4).map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="flex border-b border-slate-200 mb-6 gap-2 sm:gap-4 overflow-x-auto text-xs sm:text-sm">
        <button
          onClick={() => setActiveTab('components')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'components'
              ? 'border-purple-600 text-purple-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Layers className="w-4 h-4" />
          <span>Component Explorer ({components.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('logic')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'logic'
              ? 'border-purple-600 text-purple-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Binary className="w-4 h-4" />
          <span>Code Logic Inspector</span>
        </button>

        <button
          onClick={() => setActiveTab('interactions')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'interactions'
              ? 'border-purple-600 text-purple-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Network className="w-4 h-4" />
          <span>Component Interactions ({interactions.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('architecture')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'architecture'
              ? 'border-purple-600 text-purple-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Cpu className="w-4 h-4" />
          <span>Architecture Overview</span>
        </button>
      </div>

      {/* Tab 1: Component Explorer */}
      {activeTab === 'components' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Left: Component List */}
          <div className="space-y-2 md:col-span-1 border-r border-slate-100 pr-0 md:pr-4">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block mb-2">
              Selected Primary Components
            </span>
            {components.map((comp, idx) => {
              const isSelected = selectedComponentIdx === idx;
              return (
                <button
                  key={idx}
                  onClick={() => setSelectedComponentIdx(idx)}
                  className={`w-full text-left p-3 rounded-xl border transition flex items-start justify-between gap-2 ${
                    isSelected
                      ? 'border-purple-600 bg-purple-50/50 shadow-sm'
                      : 'border-slate-200 bg-white hover:border-purple-200'
                  }`}
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-bold text-xs text-slate-900">{comp.name}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-bold bg-slate-100 text-slate-600 border border-slate-200">
                        {comp.category}
                      </span>
                    </div>
                    <div className="text-[11px] font-mono text-slate-500 truncate max-w-[200px]">
                      {comp.file_path}
                    </div>
                  </div>
                  <span className="text-xs font-bold text-purple-700 bg-purple-100/70 px-2 py-0.5 rounded-full">
                    {comp.importance_score}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Right: Component Detail */}
          <div className="md:col-span-2 space-y-4">
            {currentComponent.name ? (
              <>
                <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                  <div>
                    <h4 className="text-base font-bold text-slate-900">{currentComponent.name}</h4>
                    <span className="text-xs font-mono text-slate-500">{currentComponent.file_path}</span>
                  </div>
                  <span className="px-2.5 py-1 rounded-md text-xs font-semibold bg-purple-50 text-purple-700 border border-purple-200">
                    {currentComponent.category} layer
                  </span>
                </div>

                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-1.5">
                  <span className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                    Primary Responsibility
                  </span>
                  <p className="text-xs sm:text-sm text-slate-800 leading-relaxed">
                    {currentComponent.primary_responsibility}
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="p-3.5 rounded-xl bg-indigo-50/40 border border-indigo-100 space-y-1">
                    <span className="text-xs font-bold text-indigo-900 uppercase tracking-wider block">
                      Why It Matters
                    </span>
                    <p className="text-xs text-slate-700 leading-relaxed">
                      {currentComponent.why_important}
                    </p>
                  </div>

                  <div className="p-3.5 rounded-xl bg-purple-50/40 border border-purple-100 space-y-1">
                    <span className="text-xs font-bold text-purple-900 uppercase tracking-wider block">
                      Inputs & Outputs
                    </span>
                    <p className="text-xs text-slate-700 leading-relaxed">
                      {currentComponent.inputs_and_outputs}
                    </p>
                  </div>
                </div>

                {/* Key symbols */}
                {currentComponent.key_classes_and_functions?.length > 0 && (
                  <div>
                    <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-2">
                      Key Classes & Functions
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {currentComponent.key_classes_and_functions.map((sym, sIdx) => (
                        <span
                          key={sIdx}
                          className="px-2.5 py-1 rounded-lg bg-white border border-slate-200 text-xs font-mono text-slate-800"
                        >
                          {sym}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Static Dependencies */}
                {currentComponent.dependencies?.length > 0 && (
                  <div>
                    <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block mb-2">
                      Component Dependencies
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {currentComponent.dependencies.map((dep, dIdx) => (
                        <span
                          key={dIdx}
                          className="px-2 py-0.5 rounded bg-slate-100 text-[11px] font-mono text-slate-700 border border-slate-200"
                        >
                          → {dep}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="text-sm text-slate-500 text-center py-10">Select a component to inspect details.</div>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: Code Logic Inspector */}
      {activeTab === 'logic' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-slate-100">
            <p className="text-xs text-slate-500">
              Inspecting grounded code logic for key classes, functions, and methods.
            </p>
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1 max-w-full">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mr-1">Component:</span>
              <button
                onClick={() => setSelectedComponentIdx(-1)}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold whitespace-nowrap transition ${
                  selectedComponentIdx === -1
                    ? 'bg-purple-600 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                All ({components.length})
              </button>
              {components.map((comp, idx) => (
                <button
                  key={idx}
                  onClick={() => setSelectedComponentIdx(idx)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-semibold whitespace-nowrap transition flex items-center gap-1 ${
                    selectedComponentIdx === idx
                      ? 'bg-purple-600 text-white shadow-sm'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  <span>{comp.name}</span>
                  {comp.is_deterministic && (
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" title="Static metadata fallback" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {(selectedComponentIdx === -1
            ? components
            : [components[selectedComponentIdx] || components[0]]
          ).filter(Boolean).map((comp, compIdx) => (
            <div key={compIdx} className="space-y-3">
              <div className="flex items-center justify-between gap-2 pb-1 border-b border-slate-100">
                <div className="flex items-center gap-2">
                  <FileCode className="w-4 h-4 text-purple-600" />
                  <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                    {comp.name} ({comp.file_path})
                  </h4>
                </div>
                {comp.is_deterministic && (
                  <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-amber-50 text-amber-800 border border-amber-200">
                    Static Metadata Fallback
                  </span>
                )}
              </div>

              {comp.code_explanations?.length > 0 ? (
                comp.code_explanations.map((expl, explIdx) => {
                  const itemKey = `${compIdx}-${explIdx}`;
                  const isExpanded = expandedCodeIdx === itemKey;

                  return (
                    <div
                      key={explIdx}
                      className="p-4 rounded-xl border border-slate-200 hover:border-purple-200 bg-white transition space-y-2.5"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono font-bold text-sm text-purple-900">{expl.name}</span>
                            <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-purple-50 text-purple-700 border border-purple-100">
                              {expl.symbol_type}
                            </span>
                            <span className="px-2 py-0.5 rounded font-mono text-[10px] text-slate-500 bg-slate-100">
                              L{expl.line_start}–{expl.line_end}
                            </span>
                            {expl.is_deterministic && (
                              <span className="px-1.5 py-0.5 rounded text-[9px] uppercase font-bold bg-amber-50 text-amber-700 border border-amber-200">
                                Static Metadata
                              </span>
                            )}
                          </div>
                          {expl.signature && (
                            <div className="font-mono text-xs text-slate-500 bg-slate-50 px-2 py-1 rounded inline-block">
                              {expl.signature}
                            </div>
                          )}
                          <p className="text-xs text-slate-700 leading-relaxed font-medium">
                            {expl.summary}
                          </p>
                        </div>

                        <button
                          onClick={() => setExpandedCodeIdx(isExpanded ? null : itemKey)}
                          className="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition"
                          title="Toggle step-by-step logic details"
                        >
                          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                        </button>
                      </div>

                      {/* Expanded Logic Details */}
                      {isExpanded && (
                        <div className="mt-3 pt-3 border-t border-slate-100 space-y-3">
                          <div className="p-3 rounded-lg bg-slate-50/80 border border-slate-200 text-xs text-slate-800 leading-relaxed">
                            <span className="font-bold text-slate-700 block mb-1">Step-by-step execution logic:</span>
                            {expl.logic_explanation}
                          </div>

                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                            <div className="p-2.5 rounded-lg bg-indigo-50/40 border border-indigo-100">
                              <span className="font-bold text-indigo-900 block mb-1">Parameters & Return:</span>
                              <span className="text-slate-700">{expl.parameters_and_returns}</span>
                            </div>

                            {expl.internal_calls?.length > 0 && (
                              <div className="p-2.5 rounded-lg bg-purple-50/40 border border-purple-100">
                                <span className="font-bold text-purple-900 block mb-1">Key Internal Calls:</span>
                                <div className="flex flex-wrap gap-1">
                                  {expl.internal_calls.map((call, cIdx) => (
                                    <span key={cIdx} className="px-1.5 py-0.5 rounded bg-white font-mono text-[11px] text-purple-800 border border-purple-200">
                                      {call}()
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>

                          {/* Code Evidence Reference */}
                          {expl.supporting_evidence?.length > 0 && (
                            <div className="pt-2 flex items-center gap-1.5 text-xs text-slate-500 flex-wrap">
                              <span className="text-[10px] uppercase font-bold text-slate-400">Source Evidence:</span>
                              {expl.supporting_evidence.map((ev, evIdx) => (
                                <span
                                  key={evIdx}
                                  className="inline-flex items-center gap-1 font-mono text-[11px] px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700"
                                >
                                  <FileCode className="w-3 h-3 text-slate-400" />
                                  <span>{ev.file_path}</span>
                                  {ev.line_start && (
                                    <span className="text-purple-700 font-bold">
                                      L{ev.line_start}{ev.line_end ? `–${ev.line_end}` : ''}
                                    </span>
                                  )}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              ) : (
                <div className="text-xs text-slate-400 italic">No code explanations recorded for this component.</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Tab 3: Component Interactions */}
      {activeTab === 'interactions' && (
        <div className="space-y-3">
          <p className="text-xs text-slate-500 mb-2">
            Verified inter-component interactions based on static dependency imports and resolved call-graph relationships.
          </p>

          {interactions.length > 0 ? (
            interactions.map((inter, idx) => (
              <div
                key={idx}
                className="p-4 rounded-xl border border-slate-200 bg-white hover:border-purple-200 transition space-y-2"
              >
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 font-mono text-xs font-bold text-slate-800 flex-wrap">
                    <span className="text-purple-900 bg-purple-50 px-2.5 py-1 rounded-lg border border-purple-100">
                      {inter.source_component}
                    </span>
                    <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                    <span className="text-indigo-900 bg-indigo-50 px-2.5 py-1 rounded-lg border border-indigo-100">
                      {inter.target_component}
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-slate-100 text-slate-600 border border-slate-200">
                      {inter.interaction_type}
                    </span>
                  </div>

                  {inter.is_confirmed ? (
                    <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      <span>Confirmed (Static Edge)</span>
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-slate-100 text-slate-600 border border-slate-200">
                      Inferred (Conceptual)
                    </span>
                  )}
                </div>

                <p className="text-xs text-slate-700 leading-relaxed">
                  {inter.description}
                </p>

                {inter.supporting_evidence?.length > 0 && (
                  <div className="pt-1 flex items-center gap-1.5 text-[11px] text-slate-500 flex-wrap font-mono">
                    <span className="text-[10px] uppercase font-bold text-slate-400">Evidence:</span>
                    {inter.supporting_evidence.map((ev, evIdx) => (
                      <span
                        key={evIdx}
                        className="px-2 py-0.5 rounded bg-slate-50 border border-slate-200 text-slate-600"
                      >
                        {ev.file_path}{ev.line_start ? `:L${ev.line_start}` : ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))
          ) : (
            <div className="text-xs text-slate-500 text-center py-8">
              No cross-component interactions recorded.
            </div>
          )}
        </div>
      )}

      {/* Tab 4: Architecture Overview */}
      {activeTab === 'architecture' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-purple-50/50 border border-purple-100 space-y-2">
            <h4 className="text-xs font-bold text-purple-900 uppercase tracking-wider flex items-center gap-1.5">
              <Cpu className="w-4 h-4 text-purple-600" />
              <span>Architectural Synthesis</span>
            </h4>
            <p className="text-xs sm:text-sm text-slate-800 leading-relaxed">
              {codeUnderstanding.architecture_overview || 'No architectural overview generated.'}
            </p>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-600 space-y-1.5">
            <span className="font-bold text-slate-700 block">Analysis Metrics:</span>
            <div>• Selected Primary Components: <span className="font-semibold">{components.length}</span></div>
            <div>• Inter-Component Interactions: <span className="font-semibold">{interactions.length}</span></div>
            <div>• Generation Provider / Model: <span className="font-semibold">{codeUnderstanding.provider || 'none'} / {codeUnderstanding.model || 'none'}</span></div>
          </div>
        </div>
      )}
    </div>
  );
}
