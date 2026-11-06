import React, { useState } from 'react';
import {
  FileText,
  Sparkles,
  Clock,
  Users,
  Target,
  BookOpen,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Layers,
  GitBranch,
  FileCode,
  ShieldCheck,
  Terminal,
  Info,
  Volume2,
  Quote,
  Cpu,
  AlertTriangle,
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

/**
 * Maps narrative section purpose to readable labels and accent colors.
 */
const PURPOSE_BADGES = {
  hook: { label: 'Hook & Problem', bg: 'bg-amber-50 text-amber-700 border-amber-200' },
  introduction: { label: 'Introduction', bg: 'bg-blue-50 text-blue-700 border-blue-200' },
  problem: { label: 'Problem Context', bg: 'bg-rose-50 text-rose-700 border-rose-200' },
  architecture_overview: { label: 'Architecture Overview', bg: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
  technology_overview: { label: 'Technology Stack', bg: 'bg-cyan-50 text-cyan-700 border-cyan-200' },
  component_deep_dive: { label: 'Component Deep Dive', bg: 'bg-purple-50 text-purple-700 border-purple-200' },
  workflow: { label: 'Execution Workflow', bg: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  data_flow: { label: 'Data Flow', bg: 'bg-teal-50 text-teal-700 border-teal-200' },
  conclusion: { label: 'Summary & Takeaway', bg: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  other: { label: 'Section', bg: 'bg-slate-100 text-slate-700 border-slate-200' },
};

export default function EducationalScriptCard({
  script,
  isLoading,
  onGenerate,
  error,
  isPrerequisiteReady = true,
  readOnly = false,
}) {
  const [expandedSections, setExpandedSections] = useState({});
  const [showMetadata, setShowMetadata] = useState(false);
  const [showCaveats, setShowCaveats] = useState(false);

  const toggleSection = (idx) => {
    setExpandedSections((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  const expandAll = () => {
    if (!script?.sections) return;
    const all = {};
    script.sections.forEach((_, i) => {
      all[i] = true;
    });
    setExpandedSections(all);
  };

  const collapseAll = () => {
    setExpandedSections({});
  };

  // 1. Not yet generated and not loading
  if (!script && !isLoading) {
    return (
      <div className="bg-gradient-to-br from-blue-50/70 via-white to-indigo-50/50 rounded-2xl border border-blue-200 p-6 sm:p-8 shadow-sm mb-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-blue-600 text-white flex items-center justify-center mx-auto mb-4 shadow-md shadow-blue-200">
          <FileText className="w-6 h-6" />
        </div>
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 border border-blue-200 mb-3">
          <Sparkles className="w-3.5 h-3.5 text-blue-600" />
          <span>Stage 05 • AI Educational Narration Script</span>
        </div>
        <h3 className="text-lg font-bold text-slate-900 mb-2">
          Generate Evidence-Grounded Educational Script
        </h3>
        <p className="text-sm text-slate-600 max-w-xl mx-auto mb-6 leading-relaxed">
          Synthesize repository architecture, code components, and execution workflows into a grounded
          60–90 second educational video narration script for developer-focused learning.
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
            <span>Waiting for repository knowledge consolidation</span>
          </div>
        ) : !readOnly && (
          <button
            onClick={() => onGenerate && onGenerate(false)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm shadow-sm transition transform active:scale-95"
          >
            <FileText className="w-4 h-4" />
            <span>Generate Educational Script</span>
          </button>
        )}
      </div>
    );
  }

  // 2. Loading State
  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-blue-200 p-8 shadow-sm mb-6 text-center animate-pulse">
        <div className="w-12 h-12 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center mx-auto mb-4">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-600" />
        </div>
        <h3 className="text-base font-bold text-slate-900 mb-1">
          Generating Educational Narration Script...
        </h3>
        <p className="text-xs text-slate-500 max-w-md mx-auto">
          Synthesizing repository architecture, code components, and workflow steps into a timed 60–90s technical explainer script using Groq.
        </p>
      </div>
    );
  }

  // 3. Render Script Content
  const totalSeconds = script.total_estimated_duration_seconds || 0;
  const sections = script.sections || [];
  const totalWords = sections.reduce((acc, s) => {
    const text = s.narration_text || '';
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    return acc + words;
  }, 0);
  const avgWpm = totalSeconds > 0 ? Math.round((totalWords * 60) / totalSeconds) : 0;

  return (
    <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-6 sm:p-8 mb-6 transition-all">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-100">
        <div className="flex items-start gap-3.5">
          <div className="w-11 h-11 rounded-xl bg-blue-600 text-white flex items-center justify-center flex-shrink-0 shadow-md shadow-blue-200 mt-0.5">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                <Sparkles className="w-3 h-3 text-blue-600" />
                <span>Stage 05 • Educational Script</span>
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">
                <Clock className="w-3 h-3 text-slate-500" />
                <span>{totalSeconds.toFixed(1)}s Narration</span>
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">
                <Volume2 className="w-3 h-3 text-slate-500" />
                <span>{totalWords} words (~{avgWpm} wpm)</span>
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                <ShieldCheck className="w-3 h-3 text-emerald-600" />
                <span>Static Analysis Grounded</span>
              </span>
            </div>
            <h3 className="text-xl font-bold text-slate-900 tracking-tight">
              {script.title || 'Educational Explainer Script'}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Repository: <span className="font-mono font-medium text-slate-700">{script.repository_name}</span>
            </p>
          </div>
        </div>

        {!readOnly && (
          <div className="flex items-center gap-2 self-start sm:self-auto">
            <button
              onClick={() => onGenerate && onGenerate(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-medium transition shadow-2xs"
              title="Regenerate educational script using fresh AI analysis"
            >
              <RefreshCw className="w-3.5 h-3.5 text-slate-500" />
              <span>Regenerate Script</span>
            </button>
          </div>
        )}
      </div>

      {/* Error alert if regeneration produced error */}
      {error && (
        <div className="mt-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-600" />
          <span>{error}</span>
        </div>
      )}

      {/* Overview Grid: Intro, Audience, Objectives */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
        {/* Introduction */}
        <div className="p-4 rounded-xl bg-slate-50 border border-slate-100">
          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700 mb-2">
            <BookOpen className="w-3.5 h-3.5 text-blue-600" />
            <span>Introduction & Hook</span>
          </div>
          <p className="text-xs text-slate-600 leading-relaxed">
            {script.introduction || 'No introduction provided.'}
          </p>
        </div>

        {/* Intended Audience */}
        <div className="p-4 rounded-xl bg-slate-50 border border-slate-100">
          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700 mb-2">
            <Users className="w-3.5 h-3.5 text-blue-600" />
            <span>Target Audience</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {script.intended_audience && script.intended_audience.length > 0 ? (
              script.intended_audience.map((aud, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded-md bg-white border border-slate-200 text-slate-700 text-xs font-medium"
                >
                  {aud}
                </span>
              ))
            ) : (
              <span className="text-xs text-slate-500">Software Engineers, Technical Learners</span>
            )}
          </div>
        </div>

        {/* Learning Objectives */}
        <div className="p-4 rounded-xl bg-slate-50 border border-slate-100">
          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700 mb-2">
            <Target className="w-3.5 h-3.5 text-blue-600" />
            <span>Learning Objectives</span>
          </div>
          <ul className="space-y-1">
            {script.learning_objectives && script.learning_objectives.length > 0 ? (
              script.learning_objectives.map((obj, i) => (
                <li key={i} className="text-xs text-slate-600 flex items-start gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0 mt-0.5" />
                  <span>{obj}</span>
                </li>
              ))
            ) : (
              <li className="text-xs text-slate-500">Understand architecture and key workflows</li>
            )}
          </ul>
        </div>
      </div>

      {/* Narration Sections Header */}
      <div className="flex items-center justify-between mt-8 mb-4">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
            Narration Sections ({sections.length})
          </h4>
          <span className="text-xs text-slate-400">•</span>
          <span className="text-xs text-slate-500">Timed technical narration breakdown</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={expandAll}
            className="text-blue-600 hover:text-blue-800 font-medium transition"
          >
            Expand All
          </button>
          <span className="text-slate-300">|</span>
          <button
            onClick={collapseAll}
            className="text-slate-500 hover:text-slate-700 font-medium transition"
          >
            Collapse All
          </button>
        </div>
      </div>

      {/* Sections Accordion List */}
      <div className="space-y-3">
        {sections.map((section, idx) => {
          const isExpanded = !!expandedSections[idx];
          const purposeConfig = PURPOSE_BADGES[section.purpose] || PURPOSE_BADGES.other;
          const sectionWords = section.narration_text ? section.narration_text.trim().split(/\s+/).length : 0;
          const sectionDuration = section.estimated_duration_seconds || 0;

          return (
            <div
              key={section.section_id || idx}
              className={`rounded-xl border transition-all ${
                isExpanded ? 'border-blue-200 bg-blue-50/20 shadow-2xs' : 'border-slate-200/90 bg-white hover:border-slate-300'
              }`}
            >
              {/* Section Header Button */}
              <button
                onClick={() => toggleSection(idx)}
                className="w-full px-4 py-3.5 flex items-center justify-between text-left gap-3"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="w-6 h-6 rounded-lg bg-blue-100 text-blue-700 font-mono font-bold text-xs flex items-center justify-center flex-shrink-0">
                    {section.order || idx + 1}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-slate-900 text-sm truncate">
                        {section.title || `Section ${idx + 1}`}
                      </span>
                      <span className={`px-2 py-0.5 rounded-full text-2xs font-semibold border ${purposeConfig.bg}`}>
                        {purposeConfig.label}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="text-xs font-mono font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md">
                    {sectionDuration.toFixed(1)}s ({sectionWords}w)
                  </span>
                  {isExpanded ? (
                    <ChevronUp className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-slate-400" />
                  )}
                </div>
              </button>

              {/* Section Expanded Details */}
              {isExpanded && (
                <div className="px-4 pb-4 pt-1 border-t border-slate-100 space-y-3.5">
                  {/* Spoken Narration */}
                  <div className="p-3.5 rounded-lg bg-white border border-blue-100 shadow-2xs">
                    <div className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-blue-700 mb-1.5">
                      <Quote className="w-3 h-3 text-blue-600" />
                      <span>Spoken Voiceover Narration</span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-800 leading-relaxed italic font-serif">
                      "{section.narration_text}"
                    </p>
                  </div>

                  {/* Transition to next */}
                  {section.transition_to_next && (
                    <div className="text-xs text-slate-500 flex items-center gap-1.5 px-1">
                      <span className="font-semibold text-slate-600">Transition:</span>
                      <span className="italic">"{section.transition_to_next}"</span>
                    </div>
                  )}

                  {/* Grounded Claims / Evidence References */}
                  {(section.claims?.length > 0 || section.evidence?.length > 0) && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1">
                      {/* Claims */}
                      {section.claims?.length > 0 && (
                        <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200/70 text-xs">
                          <div className="font-semibold text-slate-700 mb-1.5 flex items-center gap-1">
                            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                            <span>Grounded Claims</span>
                          </div>
                          <ul className="space-y-1 text-2xs text-slate-600">
                            {section.claims.map((claim, ci) => (
                              <li key={ci} className="flex items-start gap-1">
                                <span className="text-emerald-500 font-bold">•</span>
                                <span>{claim.statement}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Evidence Files */}
                      {section.evidence?.length > 0 && (
                        <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200/70 text-xs">
                          <div className="font-semibold text-slate-700 mb-1.5 flex items-center gap-1">
                            <FileCode className="w-3.5 h-3.5 text-blue-600" />
                            <span>Verified Source Evidence</span>
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {section.evidence.map((ev, ei) => (
                              <span
                                key={ei}
                                className="px-1.5 py-0.5 rounded bg-white border border-slate-200 text-2xs font-mono text-slate-700"
                                title={`Lines ${ev.line_start || 1}-${ev.line_end || ''}`}
                              >
                                {sanitizePath(ev.file_path)}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Related Components or Workflow References */}
                  {(section.related_components?.length > 0 || section.related_workflow_steps?.length > 0) && (
                    <div className="flex flex-wrap gap-2 text-2xs pt-1">
                      {section.related_components?.map((c, ci) => (
                        <span key={ci} className="px-2 py-0.5 rounded-md bg-purple-50 text-purple-700 border border-purple-200 flex items-center gap-1">
                          <Layers className="w-3 h-3 text-purple-600" />
                          <span>Component: {c.component_id}</span>
                        </span>
                      ))}
                      {section.related_workflow_steps?.map((w, wi) => (
                        <span key={wi} className="px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1">
                          <GitBranch className="w-3 h-3 text-emerald-600" />
                          <span>Workflow Step {w.step_number || ''}: {w.symbol_name || w.workflow_id}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Script Conclusion */}
      {script.conclusion && (
        <div className="mt-6 p-4 rounded-xl bg-slate-50 border border-slate-100">
          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700 mb-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
            <span>Conclusion & Next Steps</span>
          </div>
          <p className="text-xs text-slate-600 leading-relaxed font-serif italic">
            "{script.conclusion}"
          </p>
        </div>
      )}

      {/* Provenance & Static Analysis Disclaimers (Collapsible footer) */}
      <div className="mt-6 pt-4 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
        <div className="flex items-center gap-4">
          <button
            onClick={() => setShowCaveats(!showCaveats)}
            className="flex items-center gap-1 text-slate-500 hover:text-slate-800 font-medium transition"
          >
            <Info className="w-3.5 h-3.5" />
            <span>Static Analysis Caveats ({script.static_analysis_caveats?.length || 2})</span>
          </button>
          {script.metadata?.provider && (
            <button
              onClick={() => setShowMetadata(!showMetadata)}
              className="flex items-center gap-1 text-slate-500 hover:text-slate-800 font-medium transition"
            >
              <Cpu className="w-3.5 h-3.5 text-blue-600" />
              <span>AI Provenance ({script.metadata.provider}/{script.metadata.model || 'model'})</span>
            </button>
          )}
        </div>

        <span className="text-2xs text-slate-400 font-mono">
          Schema v{script.schema_version || '1.0'} • ID: {script.script_id}
        </span>
      </div>

      {/* Collapsible Caveats Card */}
      {showCaveats && (
        <div className="mt-3 p-3.5 rounded-xl bg-amber-50/70 border border-amber-200 text-xs text-amber-900 space-y-1.5">
          <div className="font-semibold flex items-center gap-1 text-amber-800">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Static Analysis & Grounding Invariants</span>
          </div>
          <ul className="list-disc list-inside space-y-1 text-2xs text-amber-800/90">
            {(script.static_analysis_caveats || []).map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Collapsible AI Metadata Card */}
      {showMetadata && script.metadata && (
        <div className="mt-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200 text-2xs text-slate-600 grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono">
          <div>
            <span className="text-slate-400 block">Provider:</span>
            <span className="font-medium text-slate-800">{script.metadata.provider || 'Groq'}</span>
          </div>
          <div>
            <span className="text-slate-400 block">Model:</span>
            <span className="font-medium text-slate-800">{script.metadata.model || 'llama-3.3-70b-versatile'}</span>
          </div>
          <div>
            <span className="text-slate-400 block">Latency:</span>
            <span className="font-medium text-slate-800">{(script.metadata.latency_ms || 0).toFixed(0)} ms</span>
          </div>
          <div>
            <span className="text-slate-400 block">Total Tokens:</span>
            <span className="font-medium text-slate-800">{script.metadata.token_usage?.total_tokens || '—'}</span>
          </div>
        </div>
      )}
    </div>
  );
}
