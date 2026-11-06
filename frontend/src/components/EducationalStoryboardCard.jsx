import React, { useState } from 'react';
import {
  Clapperboard,
  Film,
  Clock,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Layers,
  FileCode,
  Layout,
  ArrowRight,
  Eye,
  Type,
  Volume2,
  Info,
  ShieldCheck,
  Tv,
  Monitor,
  Code2,
  GitBranch,
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
 * Badges and visual styling for suggested visual types.
 */
const VISUAL_TYPE_BADGES = {
  title_card: { label: 'Title Card', bg: 'bg-indigo-50 text-indigo-700 border-indigo-200', icon: Layout },
  architecture_diagram: { label: 'Architecture Diagram', bg: 'bg-blue-50 text-blue-700 border-blue-200', icon: Layers },
  component_diagram: { label: 'Component Diagram', bg: 'bg-purple-50 text-purple-700 border-purple-200', icon: Layers },
  code_walkthrough: { label: 'Code Walkthrough', bg: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: Code2 },
  workflow_diagram: { label: 'Workflow Diagram', bg: 'bg-amber-50 text-amber-700 border-amber-200', icon: GitBranch },
  data_flow_visualization: { label: 'Data Flow Animation', bg: 'bg-teal-50 text-teal-700 border-teal-200', icon: GitBranch },
  technology_overview: { label: 'Tech Stack View', bg: 'bg-cyan-50 text-cyan-700 border-cyan-200', icon: Layout },
  summary_card: { label: 'Key Takeaways', bg: 'bg-violet-50 text-violet-700 border-violet-200', icon: CheckCircle2 },
  other: { label: 'Visual Scene', bg: 'bg-slate-100 text-slate-700 border-slate-200', icon: Eye },
};

export default function EducationalStoryboardCard({
  storyboard,
  isLoading,
  onGenerate,
  error,
  isScriptAvailable = false,
  readOnly = false,
}) {
  const [expandedScenes, setExpandedScenes] = useState({});
  const [showMetadata, setShowMetadata] = useState(false);

  const toggleScene = (idx) => {
    setExpandedScenes((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  const expandAll = () => {
    if (!storyboard?.scenes) return;
    const all = {};
    storyboard.scenes.forEach((_, i) => {
      all[i] = true;
    });
    setExpandedScenes(all);
  };

  const collapseAll = () => {
    setExpandedScenes({});
  };

  // 1. Not yet generated and not loading
  if (!storyboard && !isLoading) {
    return (
      <div className="bg-gradient-to-br from-indigo-50/70 via-white to-purple-50/50 rounded-2xl border border-indigo-200 p-6 sm:p-8 shadow-sm mb-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-indigo-600 text-white flex items-center justify-center mx-auto mb-4 shadow-md shadow-indigo-200">
          <Clapperboard className="w-6 h-6" />
        </div>
        <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800 border border-indigo-200 mb-3">
          <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
          <span>Stage 06 • Educational Storyboard Plan</span>
        </div>
        <h3 className="text-lg font-bold text-slate-900 mb-2">
          Generate Timed Visual Storyboard
        </h3>
        <p className="text-sm text-slate-600 max-w-xl mx-auto mb-6 leading-relaxed">
          Translate the educational narration script into an ordered sequence of timed visual scenes,
          specifying diagrams, code snippets, on-screen text, and scene transitions.
        </p>

        {error && (
          <div className="max-w-md mx-auto mb-5 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2 text-left">
            <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-600" />
            <span>{error}</span>
          </div>
        )}

        {!isScriptAvailable ? (
          <div className="max-w-md mx-auto mb-2 p-3 rounded-xl bg-slate-100/90 border border-slate-200 text-slate-600 text-xs flex items-center gap-2 justify-center">
            <Clock className="w-4 h-4 text-slate-500" />
            <span>Generate an Educational Script (Stage 05) first to unlock Storyboard generation</span>
          </div>
        ) : !readOnly && (
          <button
            onClick={() => onGenerate && onGenerate(false)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm shadow-sm transition transform active:scale-95"
          >
            <Clapperboard className="w-4 h-4" />
            <span>Generate Educational Storyboard</span>
          </button>
        )}
      </div>
    );
  }

  // 2. Loading State
  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-indigo-200 p-8 shadow-sm mb-6 text-center animate-pulse">
        <div className="w-12 h-12 rounded-xl bg-indigo-100 text-indigo-600 flex items-center justify-center mx-auto mb-4">
          <RefreshCw className="w-6 h-6 animate-spin text-indigo-600" />
        </div>
        <h3 className="text-base font-bold text-slate-900 mb-1">
          Generating Educational Storyboard...
        </h3>
        <p className="text-xs text-slate-500 max-w-md mx-auto">
          Decomposing script sections into timed visual scenes, aligning narration excerpts, layout hints, and on-screen callouts.
        </p>
      </div>
    );
  }

  // 3. Render Storyboard Content
  const totalSeconds = storyboard.total_estimated_duration_seconds || 0;
  const scenes = storyboard.scenes || [];
  const format = storyboard.video_format || {};
  const orientation = format.orientation || 'landscape';
  const aspectRatio = format.aspect_ratio || '16:9';

  return (
    <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-6 sm:p-8 mb-6 transition-all">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-100">
        <div className="flex items-start gap-3.5">
          <div className="w-11 h-11 rounded-xl bg-indigo-600 text-white flex items-center justify-center flex-shrink-0 shadow-md shadow-indigo-200 mt-0.5">
            <Clapperboard className="w-5 h-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
                <Sparkles className="w-3 h-3 text-indigo-600" />
                <span>Stage 06 • Educational Storyboard</span>
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">
                <Clock className="w-3 h-3 text-slate-500" />
                <span>{totalSeconds.toFixed(1)}s Total Duration</span>
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">
                <Monitor className="w-3 h-3 text-slate-500" />
                <span className="capitalize">{orientation} ({aspectRatio})</span>
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
                <Layout className="w-3 h-3 text-amber-600" />
                <span>Structured Visual Plan</span>
              </span>
            </div>
            <h3 className="text-xl font-bold text-slate-900 tracking-tight">
              {storyboard.title || 'Educational Video Storyboard'}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Script ID: <span className="font-mono font-medium text-slate-700">{storyboard.script_id}</span> • {scenes.length} Scenes
            </p>
          </div>
        </div>

        {!readOnly && (
          <div className="flex items-center gap-2 self-start sm:self-auto">
            <button
              onClick={() => onGenerate && onGenerate(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-medium transition shadow-2xs"
              title="Regenerate storyboard from the current stored script"
            >
              <RefreshCw className="w-3.5 h-3.5 text-slate-500" />
              <span>Regenerate Storyboard</span>
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

      {/* Educational Notice Banner */}
      <div className="mt-5 p-3.5 rounded-xl bg-slate-50 border border-slate-200/80 flex items-center gap-3 text-xs text-slate-600">
        <Info className="w-4 h-4 text-indigo-600 flex-shrink-0" />
        <div className="leading-relaxed">
          <span className="font-semibold text-slate-800">Visual Production Blueprint:</span> This storyboard specifies
          timed scenes, visual types, on-screen text, and narration cues. Actual rendering of diagrams, visual animations,
          and speech audio is scheduled for downstream pipeline stages.
        </div>
      </div>

      {/* Scenes Header */}
      <div className="flex items-center justify-between mt-8 mb-4">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
            Timed Visual Scenes ({scenes.length})
          </h4>
          <span className="text-xs text-slate-400">•</span>
          <span className="text-xs text-slate-500">Ordered camera & slide progression</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={expandAll}
            className="text-indigo-600 hover:text-indigo-800 font-medium transition"
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

      {/* Ordered Scene Cards */}
      <div className="space-y-4">
        {scenes.map((scene, idx) => {
          const isExpanded = !!expandedScenes[idx];
          const badgeConfig = VISUAL_TYPE_BADGES[scene.visual_type] || VISUAL_TYPE_BADGES.other;
          const BadgeIcon = badgeConfig.icon;
          const sceneDuration = scene.estimated_duration_seconds || 0;

          return (
            <div
              key={scene.scene_id || idx}
              className={`rounded-xl border transition-all ${
                isExpanded ? 'border-indigo-200 bg-indigo-50/15 shadow-2xs' : 'border-slate-200/90 bg-white hover:border-slate-300'
              }`}
            >
              {/* Scene Card Header Button */}
              <button
                onClick={() => toggleScene(idx)}
                className="w-full px-4 py-3.5 flex items-center justify-between text-left gap-3"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="w-7 h-7 rounded-lg bg-indigo-100 text-indigo-700 font-mono font-bold text-xs flex items-center justify-center flex-shrink-0">
                    #{scene.scene_number || idx + 1}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-slate-900 text-sm truncate">
                        {scene.title || `Scene ${idx + 1}`}
                      </span>
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-semibold border ${badgeConfig.bg}`}>
                        <BadgeIcon className="w-3 h-3" />
                        <span>{badgeConfig.label}</span>
                      </span>
                      {scene.layout_hint && (
                        <span className="px-1.5 py-0.5 rounded text-2xs font-mono text-slate-500 bg-slate-100">
                          {scene.layout_hint}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="text-xs font-mono font-medium text-slate-600 bg-slate-100 px-2 py-0.5 rounded-md">
                    {sceneDuration.toFixed(1)}s
                  </span>
                  {isExpanded ? (
                    <ChevronUp className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-slate-400" />
                  )}
                </div>
              </button>

              {/* Scene Expanded Body */}
              {isExpanded && (
                <div className="px-4 pb-4 pt-1 border-t border-slate-100 space-y-3.5">
                  {/* Visual Description & Purpose */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {/* Visual Plan */}
                    <div className="p-3.5 rounded-lg bg-white border border-indigo-100 shadow-2xs">
                      <div className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-indigo-700 mb-1.5">
                        <Eye className="w-3 h-3 text-indigo-600" />
                        <span>Visual Description</span>
                      </div>
                      <p className="text-xs text-slate-800 leading-relaxed font-sans">
                        {scene.visual_description}
                      </p>
                    </div>

                    {/* Scene Purpose & Script Binding */}
                    <div className="p-3.5 rounded-lg bg-slate-50 border border-slate-200/70">
                      <div className="flex items-center justify-between text-2xs font-bold uppercase tracking-wider text-slate-600 mb-1.5">
                        <span className="flex items-center gap-1">
                          <Layout className="w-3 h-3 text-slate-500" />
                          <span>Scene Purpose</span>
                        </span>
                        <span className="text-slate-400 font-mono">Sec: {scene.script_section_id}</span>
                      </div>
                      <p className="text-xs text-slate-700 leading-relaxed">
                        {scene.purpose}
                      </p>
                    </div>
                  </div>

                  {/* On-Screen Text Items */}
                  {scene.on_screen_text && scene.on_screen_text.length > 0 && (
                    <div className="p-3 rounded-lg bg-slate-50 border border-slate-200/70">
                      <div className="flex items-center gap-1 text-2xs font-bold uppercase tracking-wider text-slate-700 mb-2">
                        <Type className="w-3 h-3 text-indigo-600" />
                        <span>On-Screen Text & Callouts</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {scene.on_screen_text.map((text, ti) => (
                          <span
                            key={ti}
                            className="px-2.5 py-1 rounded-md bg-white border border-slate-200 text-slate-800 text-xs font-medium shadow-2xs"
                          >
                            {text}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Narration Reference */}
                  {scene.narration && (
                    <div className="p-3 rounded-lg bg-blue-50/40 border border-blue-100">
                      <div className="flex items-center gap-1 text-2xs font-bold uppercase tracking-wider text-blue-700 mb-1">
                        <Volume2 className="w-3 h-3 text-blue-600" />
                        <span>Synchronized Narration (Section: {scene.narration.script_section_id})</span>
                      </div>
                      <p className="text-xs text-slate-700 italic font-serif">
                        {scene.narration.excerpt ? `"${scene.narration.excerpt}"` : '(Covers complete section narration)'}
                      </p>
                    </div>
                  )}

                  {/* Related Files & Components */}
                  {(scene.related_files?.length > 0 || scene.related_components?.length > 0) && (
                    <div className="flex flex-wrap items-center gap-2 text-2xs pt-1">
                      {scene.related_files?.map((f, fi) => (
                        <span key={fi} className="px-2 py-0.5 rounded-md bg-white border border-slate-200 font-mono text-slate-700 flex items-center gap-1">
                          <FileCode className="w-3 h-3 text-blue-600" />
                          <span>{sanitizePath(f)}</span>
                        </span>
                      ))}
                      {scene.related_components?.map((c, ci) => (
                        <span key={ci} className="px-2 py-0.5 rounded-md bg-purple-50 text-purple-700 border border-purple-200 flex items-center gap-1">
                          <Layers className="w-3 h-3 text-purple-600" />
                          <span>{c.component_id}</span>
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Transition to next scene */}
                  {scene.transition_to_next && (
                    <div className="pt-2 border-t border-slate-100 flex items-center gap-1.5 text-xs text-slate-500">
                      <ArrowRight className="w-3.5 h-3.5 text-indigo-600" />
                      <span className="font-semibold text-slate-600">Scene Transition:</span>
                      <span className="italic">{scene.transition_to_next}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer & Metadata */}
      <div className="mt-8 pt-4 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1 text-slate-600 font-medium">
            <Film className="w-3.5 h-3.5 text-indigo-600" />
            <span>{scenes.length} Scenes • {totalSeconds.toFixed(1)}s Total</span>
          </span>
          {storyboard.metadata?.provider && (
            <button
              onClick={() => setShowMetadata(!showMetadata)}
              className="flex items-center gap-1 text-slate-500 hover:text-slate-800 font-medium transition"
            >
              <Cpu className="w-3.5 h-3.5 text-indigo-600" />
              <span>AI Provenance ({storyboard.metadata.provider}/{storyboard.metadata.model || 'model'})</span>
            </button>
          )}
        </div>

        <span className="text-2xs text-slate-400 font-mono">
          Schema v{storyboard.schema_version || '1.0'} • ID: {storyboard.storyboard_id}
        </span>
      </div>

      {/* Collapsible Provenance Details */}
      {showMetadata && storyboard.metadata && (
        <div className="mt-3 p-3.5 rounded-xl bg-slate-50 border border-slate-200 text-2xs text-slate-600 grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono">
          <div>
            <span className="text-slate-400 block">Provider:</span>
            <span className="font-medium text-slate-800">{storyboard.metadata.provider || 'Groq'}</span>
          </div>
          <div>
            <span className="text-slate-400 block">Model:</span>
            <span className="font-medium text-slate-800">{storyboard.metadata.model || 'llama-3.3-70b-versatile'}</span>
          </div>
          <div>
            <span className="text-slate-400 block">Latency:</span>
            <span className="font-medium text-slate-800">{(storyboard.metadata.latency_ms || 0).toFixed(0)} ms</span>
          </div>
          <div>
            <span className="text-slate-400 block">Tokens:</span>
            <span className="font-medium text-slate-800">{storyboard.metadata.token_usage?.total_tokens || '—'}</span>
          </div>
        </div>
      )}
    </div>
  );
}
