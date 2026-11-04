import React, { useState } from 'react';
import {
  Sparkles,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  Users,
  Compass,
  Layers,
  Code2,
  Video,
  FileCode,
  ArrowRight,
  RefreshCw,
  Cpu,
  Clock,
  ShieldCheck,
  Zap,
  BookOpen,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

export default function ProjectUnderstandingCard({
  understanding,
  isLoading,
  onGenerate,
  error,
}) {
  const [activeTab, setActiveTab] = useState('overview'); // 'overview' | 'features' | 'audience' | 'tech' | 'educational'
  const [expandedFeature, setExpandedFeature] = useState(null);

  // If not yet generated and not loading
  if (!understanding && !isLoading) {
    return (
      <div className="bg-gradient-to-br from-indigo-50/60 via-white to-purple-50/40 rounded-2xl border border-indigo-100 p-6 sm:p-8 shadow-sm mb-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-indigo-600 text-white flex items-center justify-center mx-auto mb-4 shadow-md shadow-indigo-200">
          <Sparkles className="w-6 h-6" />
        </div>
        <h3 className="text-lg font-bold text-slate-900 mb-2">
          AI Project Understanding Ready to Run
        </h3>
        <p className="text-sm text-slate-600 max-w-xl mx-auto mb-6 leading-relaxed">
          RepoGenie has unified code parsing, dependency graphs, and repository evidence.
          Run the AI understanding engine to extract grounded problem statements, core features,
          target audience analysis, and educational video highlights.
        </p>

        {error && (
          <div className="max-w-md mx-auto mb-5 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2 text-left">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-600" />
            <span>{error}</span>
          </div>
        )}

        <button
          onClick={() => onGenerate && onGenerate(false)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm shadow-sm transition transform active:scale-95"
        >
          <Sparkles className="w-4 h-4" />
          <span>Generate Project Understanding</span>
        </button>
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-indigo-200 p-8 shadow-sm mb-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-indigo-100 text-indigo-600 flex items-center justify-center mx-auto mb-4 animate-spin">
          <Sparkles className="w-6 h-6" />
        </div>
        <h3 className="text-base font-bold text-slate-900 mb-1">
          Generating AI Project Understanding...
        </h3>
        <p className="text-xs text-slate-500 max-w-md mx-auto">
          Reasoning over repository evidence, architectural components, and documentation.
        </p>
      </div>
    );
  }

  if (!understanding) return null;

  const identity = understanding.identity || {};
  const problem = understanding.problem_statement || {};
  const features = understanding.core_features || [];
  const audience = understanding.target_audience || {};
  const useCases = understanding.use_cases || [];
  const techStack = understanding.technology_stack || [];
  const explanation = understanding.overall_explanation || {};
  const tokenUsage = understanding.token_usage;

  return (
    <div className="bg-white rounded-2xl border border-indigo-200 shadow-sm p-6 sm:p-8 mb-6 relative overflow-hidden">
      {/* Top Header & AI Metadata */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 mb-5 border-b border-slate-100">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
              <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
              <span>Milestone 3.2 AI Understanding</span>
            </span>
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-mono font-medium bg-slate-100 text-slate-700 border border-slate-200">
              <Cpu className="w-3 h-3 text-slate-500" />
              <span>{understanding.provider}/{understanding.model}</span>
            </span>
            {understanding.latency_ms > 0 && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono text-slate-500 bg-slate-50 border border-slate-200/80">
                <Clock className="w-3 h-3 text-slate-400" />
                <span>{understanding.latency_ms} ms</span>
              </span>
            )}
            {tokenUsage && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-mono text-slate-500 bg-slate-50 border border-slate-200/80">
                <Zap className="w-3 h-3 text-amber-500" />
                <span>{tokenUsage.total_tokens.toLocaleString()} tokens</span>
              </span>
            )}
          </div>
          <h3 className="text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <span>{identity.name || 'Project'}</span>
            <span className="text-xs font-normal px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
              {identity.category || 'Software'}
            </span>
            <span className="text-xs font-normal px-2 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200">
              {identity.project_type || 'Library'}
            </span>
          </h3>
        </div>

        <button
          onClick={() => onGenerate && onGenerate(true)}
          title="Regenerate Project Understanding"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:text-slate-900 hover:bg-slate-50 text-xs font-medium transition self-start sm:self-auto"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Regenerate</span>
        </button>
      </div>

      {/* Purpose Banner */}
      <div className="p-4 rounded-xl bg-slate-50/80 border border-slate-200/80 mb-6">
        <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">
          Primary Purpose
        </h4>
        <p className="text-sm font-medium text-slate-800 leading-relaxed">
          {identity.primary_purpose || identity.short_description}
        </p>
      </div>

      {/* Navigation Tabs */}
      <div className="flex border-b border-slate-200 mb-6 overflow-x-auto gap-1 text-xs sm:text-sm font-medium">
        <button
          onClick={() => setActiveTab('overview')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'overview'
              ? 'border-indigo-600 text-indigo-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Compass className="w-4 h-4" />
          <span>Problem & Solution</span>
        </button>
        <button
          onClick={() => setActiveTab('features')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'features'
              ? 'border-indigo-600 text-indigo-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Sparkles className="w-4 h-4" />
          <span>Core Features ({features.length})</span>
        </button>
        <button
          onClick={() => setActiveTab('audience')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'audience'
              ? 'border-indigo-600 text-indigo-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Users className="w-4 h-4" />
          <span>Audience & Use Cases</span>
        </button>
        <button
          onClick={() => setActiveTab('tech')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'tech'
              ? 'border-indigo-600 text-indigo-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Layers className="w-4 h-4" />
          <span>Tech Stack Roles ({techStack.length})</span>
        </button>
        <button
          onClick={() => setActiveTab('educational')}
          className={`pb-2.5 px-3.5 border-b-2 transition whitespace-nowrap flex items-center gap-1.5 ${
            activeTab === 'educational'
              ? 'border-indigo-600 text-indigo-600 font-semibold'
              : 'border-transparent text-slate-500 hover:text-slate-700'
          }`}
        >
          <Video className="w-4 h-4" />
          <span>Educational Blueprint</span>
        </button>
      </div>

      {/* Tab 1: Problem & Solution */}
      {activeTab === 'overview' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl bg-rose-50/50 border border-rose-100 space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-bold text-rose-800 uppercase tracking-wider">
                <AlertCircle className="w-3.5 h-3.5 text-rose-600" />
                <span>Problem Addressed</span>
              </div>
              <p className="text-xs sm:text-sm text-slate-700 leading-relaxed">
                {problem.problem_addressed || 'No problem statement recorded.'}
              </p>
            </div>

            <div className="p-4 rounded-xl bg-amber-50/50 border border-amber-100 space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-bold text-amber-800 uppercase tracking-wider">
                <HelpCircle className="w-3.5 h-3.5 text-amber-600" />
                <span>Why It Matters</span>
              </div>
              <p className="text-xs sm:text-sm text-slate-700 leading-relaxed">
                {problem.why_it_matters || 'No impact explanation provided.'}
              </p>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-emerald-50/50 border border-emerald-100 space-y-1.5">
            <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-800 uppercase tracking-wider">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
              <span>How This Project Solves It</span>
            </div>
            <p className="text-xs sm:text-sm text-slate-700 leading-relaxed">
              {problem.how_project_solves_it || 'No solution mechanism provided.'}
            </p>
          </div>
        </div>
      )}

      {/* Tab 2: Core Features */}
      {activeTab === 'features' && (
        <div className="space-y-3">
          {features.map((feat, idx) => {
            const isExpanded = expandedFeature === idx;
            return (
              <div
                key={idx}
                className="p-4 rounded-xl border border-slate-200 bg-white hover:border-indigo-200 transition"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-mono text-slate-400 font-bold">#{idx + 1}</span>
                      <h5 className="text-sm font-bold text-slate-900">{feat.name}</h5>
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-indigo-50 text-indigo-700 border border-indigo-100">
                        {feat.confidence} Confidence
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 leading-relaxed">{feat.description}</p>
                    <p className="text-xs text-indigo-900 bg-indigo-50/60 p-2 rounded-lg mt-2 font-medium">
                      <span className="font-semibold text-indigo-700">User benefit: </span>
                      {feat.user_benefit}
                    </p>
                  </div>

                  {feat.supporting_evidence?.length > 0 && (
                    <button
                      onClick={() => setExpandedFeature(isExpanded ? null : idx)}
                      className="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition"
                      title="Toggle supporting evidence"
                    >
                      {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </button>
                  )}
                </div>

                {/* Evidence citations */}
                {isExpanded && feat.supporting_evidence?.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-slate-100 space-y-1.5">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Supporting Code Evidence
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {feat.supporting_evidence.map((ev, evIdx) => (
                        <span
                          key={evIdx}
                          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-100 text-slate-700 font-mono text-[11px] border border-slate-200"
                        >
                          <FileCode className="w-3 h-3 text-slate-500" />
                          <span>{ev.file_path}</span>
                          {ev.line_start && (
                            <span className="text-indigo-600 font-bold">
                              L{ev.line_start}{ev.line_end ? `-${ev.line_end}` : ''}
                            </span>
                          )}
                          <span className="text-[9px] uppercase font-bold text-slate-400">
                            [{ev.evidence_type}]
                          </span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Tab 3: Audience & Use Cases */}
      {activeTab === 'audience' && (
        <div className="space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80">
              <h5 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-indigo-600" />
                <span>Target Users</span>
              </h5>
              <ul className="space-y-1.5">
                {audience.intended_users?.map((user, idx) => (
                  <li key={idx} className="flex items-center gap-2 text-xs text-slate-700">
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-600" />
                    <span>{user}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80">
              <h5 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                <Compass className="w-3.5 h-3.5 text-indigo-600" />
                <span>Likely Needs Solved</span>
              </h5>
              <ul className="space-y-1.5">
                {audience.likely_needs?.map((need, idx) => (
                  <li key={idx} className="flex items-center gap-2 text-xs text-slate-700">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-600" />
                    <span>{need}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Use cases */}
          <div>
            <h5 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3">
              Primary Use Cases
            </h5>
            <div className="space-y-2.5">
              {useCases.map((uc, idx) => (
                <div
                  key={idx}
                  className="p-3.5 rounded-xl border border-slate-200/80 bg-white space-y-1"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-bold text-slate-400">0{idx + 1}</span>
                    <h6 className="text-xs sm:text-sm font-bold text-slate-900">{uc.name}</h6>
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">{uc.description}</p>
                  <p className="text-xs text-slate-700 font-mono bg-slate-50 p-2 rounded border border-slate-100">
                    <span className="font-semibold text-slate-500">How used: </span>
                    {uc.how_used}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Tech Stack Roles */}
      {activeTab === 'tech' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {techStack.map((tech, idx) => (
            <div
              key={idx}
              className="p-3.5 rounded-xl border border-slate-200 bg-white hover:border-slate-300 transition space-y-2"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-sm text-slate-900">
                    {tech.technology_name}
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                    {tech.category}
                  </span>
                </div>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
                    tech.status === 'confirmed'
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                      : 'bg-amber-50 text-amber-700 border border-amber-200'
                  }`}
                >
                  {tech.status}
                </span>
              </div>

              <div className="text-xs space-y-1">
                <p className="text-slate-700">
                  <span className="font-semibold text-slate-500">Role: </span>
                  {tech.role_in_project}
                </p>
                <p className="text-slate-500 text-[11px]">
                  <span className="font-semibold text-slate-400">Why used: </span>
                  {tech.why_used}
                </p>
              </div>

              {tech.supporting_evidence?.length > 0 && (
                <div className="pt-2 border-t border-slate-100 flex flex-wrap gap-1">
                  {tech.supporting_evidence.map((ev, evIdx) => (
                    <span
                      key={evIdx}
                      className="px-1.5 py-0.5 rounded bg-slate-50 text-slate-600 font-mono text-[10px] border border-slate-200"
                    >
                      {ev.file_path}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Tab 5: Educational Blueprint */}
      {activeTab === 'educational' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-indigo-50/50 border border-indigo-100 space-y-1.5">
            <span className="text-xs font-bold text-indigo-900 uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
              <span>Beginner Analogy</span>
            </span>
            <p className="text-xs sm:text-sm text-indigo-950 leading-relaxed font-medium">
              "{explanation.beginner_friendly}"
            </p>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80 space-y-1.5">
            <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
              Detailed Architecture Walkthrough
            </span>
            <p className="text-xs sm:text-sm text-slate-700 leading-relaxed">
              {explanation.detailed_explanation}
            </p>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80 space-y-1.5">
            <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
              Notable Engineering Aspects
            </span>
            <p className="text-xs sm:text-sm text-slate-700 leading-relaxed">
              {explanation.interesting_aspects}
            </p>
          </div>

          {explanation.video_demonstration_highlights?.length > 0 && (
            <div className="p-4 rounded-xl bg-white border border-slate-200 space-y-2.5">
              <span className="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                <Video className="w-3.5 h-3.5 text-indigo-600" />
                <span>Video Demonstration Scene Blueprint</span>
              </span>
              <div className="space-y-2">
                {explanation.video_demonstration_highlights.map((highlight, idx) => (
                  <div
                    key={idx}
                    className="flex items-start gap-2.5 text-xs text-slate-800 p-2 rounded-lg bg-slate-50 border border-slate-100"
                  >
                    <span className="px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 font-bold font-mono text-[10px]">
                      Scene {idx + 1}
                    </span>
                    <span className="leading-relaxed">{highlight}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
