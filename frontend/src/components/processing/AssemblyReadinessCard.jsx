import React, { useState } from 'react';
import {
  Film,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
  Clock,
  Layers,
  Image,
  Mic,
  Subtitles,
  ChevronDown,
  ChevronUp,
  FileCheck,
  ShieldAlert,
} from 'lucide-react';

export default function AssemblyReadinessCard({
  jobId,
  assemblyInput,
  isLoading,
  onValidate,
  error,
  isStoryboardAvailable = false,
  readOnly = false,
}) {
  const [expandedScenes, setExpandedScenes] = useState({});

  const toggleScene = (idx) => {
    setExpandedScenes((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  const hasData = Boolean(assemblyInput && assemblyInput.scenes && assemblyInput.scenes.length > 0);
  const readiness = assemblyInput?.readiness_report;
  const status = readiness?.status || (hasData ? 'not_ready' : 'unverified');

  const blockingIssues = readiness?.blocking_issues || [];
  const warnings = readiness?.warnings || [];

  const getStatusBadge = () => {
    if (!hasData) {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-200">
          UNVERIFIED
        </span>
      );
    }
    if (status === 'ready') {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1">
          <CheckCircle2 className="w-3.5 h-3.5" />
          READY FOR ASSEMBLY
        </span>
      );
    }
    if (status === 'ready_with_warnings') {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-1">
          <AlertTriangle className="w-3.5 h-3.5" />
          READY WITH WARNINGS
        </span>
      );
    }
    return (
      <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200 flex items-center gap-1">
        <AlertCircle className="w-3.5 h-3.5" />
        NOT READY
      </span>
    );
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-6 transition-all">
      {/* Card Header */}
      <div className="p-6 border-b border-slate-100 flex flex-wrap items-center justify-between gap-4 bg-slate-50/50">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-indigo-100 text-indigo-700 rounded-lg">
            <Film className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-900 text-lg">Video Assembly Input & Readiness</h3>
              {getStatusBadge()}
            </div>
            <p className="text-sm text-slate-500 mt-0.5">
              Physical asset verification and timeline synchronization preflight for Stage 9 Video Assembly
            </p>
          </div>
        </div>

        {/* Action Button */}
        {!readOnly && (
          <div className="flex items-center gap-3">
            <button
              onClick={() => onValidate(hasData)}
              disabled={isLoading || !isStoryboardAvailable}
              className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg shadow-sm transition-all ${
                isLoading || !isStoryboardAvailable
                  ? 'bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200'
                  : hasData
                  ? 'bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 hover:border-slate-400'
                  : 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-indigo-500/20'
              }`}
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              {isLoading
                ? 'Validating Assets...'
                : hasData
                ? 'Revalidate Assembly Package'
                : 'Validate Assembly Readiness'}
            </button>
          </div>
        )}
      </div>

      {/* Error Message Alert */}
      {error && (
        <div className="m-6 mb-0 p-4 bg-rose-50 border border-rose-200 rounded-lg flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-medium text-rose-900">Preflight Validation Error</h4>
            <p className="text-sm text-rose-700 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      {hasData ? (
        <div className="p-6 space-y-6">
          {/* Metrics Overview Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 bg-slate-50 rounded-lg border border-slate-100">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-medium uppercase tracking-wider mb-1">
                <Layers className="w-3.5 h-3.5" />
                Scenes Ready
              </div>
              <div className="text-xl font-bold text-slate-900">
                {`${readiness?.ready_scenes || 0} / ${assemblyInput.total_scenes}`}
              </div>
            </div>

            <div className="p-4 bg-slate-50 rounded-lg border border-slate-100">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-medium uppercase tracking-wider mb-1">
                <Clock className="w-3.5 h-3.5" />
                Total Duration
              </div>
              <div className="text-xl font-bold text-slate-900">
                {`${assemblyInput.total_duration_seconds.toFixed(1)}s`}
              </div>
            </div>

            <div className="p-4 bg-slate-50 rounded-lg border border-slate-100">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-medium uppercase tracking-wider mb-1">
                <Image className="w-3.5 h-3.5" />
                Visual Assets
              </div>
              <div className="text-sm font-semibold flex items-center gap-1.5 mt-1">
                {readiness?.has_visuals ? (
                  <span className="text-emerald-600 flex items-center gap-1">
                    <CheckCircle2 className="w-4 h-4" /> All Verified
                  </span>
                ) : (
                  <span className="text-rose-600 flex items-center gap-1">
                    <AlertCircle className="w-4 h-4" /> Missing / Invalid
                  </span>
                )}
              </div>
            </div>

            <div className="p-4 bg-slate-50 rounded-lg border border-slate-100">
              <div className="flex items-center gap-2 text-slate-500 text-xs font-medium uppercase tracking-wider mb-1">
                <Mic className="w-3.5 h-3.5" />
                Narration & Audio
              </div>
              <div className="text-sm font-semibold flex items-center gap-1.5 mt-1">
                {readiness?.has_narration ? (
                  <span className="text-emerald-600 flex items-center gap-1">
                    <CheckCircle2 className="w-4 h-4" /> Synced
                  </span>
                ) : (
                  <span className="text-rose-600 flex items-center gap-1">
                    <AlertCircle className="w-4 h-4" /> Incomplete
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Blocking Issues Alert */}
          {blockingIssues.length > 0 && (
            <div className="p-4 bg-rose-50 border border-rose-200 rounded-lg">
              <div className="flex items-center gap-2 text-rose-800 font-semibold text-sm mb-2">
                <ShieldAlert className="w-4 h-4 text-rose-600" />
                {`Blocking Issues (${blockingIssues.length}) — Must be resolved before assembly`}
              </div>
              <ul className="space-y-1.5 text-xs text-rose-700 pl-6 list-disc">
                {blockingIssues.map((iss, i) => (
                  <li key={i}>
                    <span className="font-mono font-medium text-rose-900">{`[${iss.code}]`}</span>{' '}
                    {iss.scene_number ? `Scene ${iss.scene_number}: ` : ''}
                    {iss.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Warnings Alert */}
          {warnings.length > 0 && (
            <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
              <div className="flex items-center gap-2 text-amber-800 font-semibold text-sm mb-2">
                <AlertTriangle className="w-4 h-4 text-amber-600" />
                {`Advisory Warnings (${warnings.length})`}
              </div>
              <ul className="space-y-1.5 text-xs text-amber-700 pl-6 list-disc">
                {warnings.map((warn, i) => (
                  <li key={i}>
                    <span className="font-mono font-medium text-amber-900">{`[${warn.code}]`}</span>{' '}
                    {warn.scene_number ? `Scene ${warn.scene_number}: ` : ''}
                    {warn.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Full-Video Subtitle Track Banner */}
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2">
              <Subtitles className="w-4 h-4 text-blue-600" />
              <span className="font-medium text-slate-700">Full-Video Subtitle Tracks:</span>
              <span className="text-slate-500">
                {assemblyInput.full_video_srt?.is_valid && assemblyInput.full_video_vtt?.is_valid
                  ? 'SRT & WebVTT compiled and ready'
                  : 'Per-scene cues available; continuous track pending'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                assemblyInput.full_video_srt?.is_valid ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-600'
              }`}>
                SRT
              </span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                assemblyInput.full_video_vtt?.is_valid ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-600'
              }`}>
                VTT
              </span>
            </div>
          </div>

          {/* Scene Assembly Timeline */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
              Scene Assembly Timeline ({assemblyInput.scenes.length} Scenes)
            </h4>
            <div className="space-y-2">
              {assemblyInput.scenes.map((scene, idx) => {
                const isExpanded = Boolean(expandedScenes[idx]);
                return (
                  <div
                    key={scene.scene_id}
                    className="border border-slate-200 rounded-lg overflow-hidden bg-white hover:border-slate-300 transition-colors"
                  >
                    <div
                      onClick={() => toggleScene(idx)}
                      className="p-3 flex items-center justify-between gap-3 cursor-pointer select-none bg-slate-50/70 hover:bg-slate-50"
                    >
                      <div className="flex items-center gap-3">
                        <span className="w-6 h-6 rounded-full bg-slate-200 text-slate-700 text-xs font-bold flex items-center justify-center shrink-0">
                          {scene.scene_number}
                        </span>
                        <div>
                          <div className="font-medium text-sm text-slate-800 flex items-center gap-2">
                            <span>{scene.title}</span>
                            <span className="text-[11px] text-slate-400 font-mono">
                              ({scene.start_seconds.toFixed(2)}s – {scene.end_seconds.toFixed(2)}s)
                            </span>
                          </div>
                          <div className="text-xs text-slate-500 font-mono">
                            {scene.section_purpose}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {/* Visual Asset Pill */}
                        <span
                          className={`text-[10px] font-medium px-2 py-0.5 rounded border ${
                            scene.visual_asset?.is_valid
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : 'bg-rose-50 text-rose-700 border-rose-200'
                          }`}
                        >
                          Visual: {scene.visual_asset?.is_valid ? 'OK' : 'Missing'}
                        </span>

                        {/* Narration Pill */}
                        <span
                          className={`text-[10px] font-medium px-2 py-0.5 rounded border ${
                            scene.is_silent
                              ? 'bg-slate-100 text-slate-600 border-slate-200'
                              : scene.narration_asset?.is_valid
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : 'bg-rose-50 text-rose-700 border-rose-200'
                          }`}
                        >
                          Audio: {scene.is_silent ? 'Silent' : scene.narration_asset?.is_valid ? 'OK' : 'Missing'}
                        </span>

                        {/* Captions Pill */}
                        <span
                          className={`text-[10px] font-medium px-2 py-0.5 rounded border ${
                            scene.is_silent
                              ? 'bg-slate-100 text-slate-600 border-slate-200'
                              : scene.caption_srt_asset?.is_valid
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : 'bg-rose-50 text-rose-700 border-rose-200'
                          }`}
                        >
                          Captions: {scene.is_silent ? 'N/A' : scene.caption_srt_asset?.is_valid ? 'OK' : 'Missing'}
                        </span>

                        {isExpanded ? (
                          <ChevronUp className="w-4 h-4 text-slate-400" />
                        ) : (
                          <ChevronDown className="w-4 h-4 text-slate-400" />
                        )}
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="p-4 border-t border-slate-100 space-y-3 bg-white text-xs text-slate-600">
                        {scene.narration_text && (
                          <div className="p-2.5 bg-slate-50 rounded border border-slate-100">
                            <span className="font-semibold text-slate-700 block mb-1">Narration Text:</span>
                            <p className="italic text-slate-600">"{scene.narration_text}"</p>
                          </div>
                        )}

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-[11px]">
                          <div className="p-2 bg-slate-50 rounded border border-slate-100">
                            <span className="font-semibold text-slate-700 block mb-0.5">Visual Asset</span>
                            {scene.visual_asset ? (
                              <div>
                                <div className="text-slate-500 font-mono truncate">{scene.visual_asset.relative_path}</div>
                                <div className="text-slate-400 mt-0.5">{(scene.visual_asset.file_size_bytes / 1024).toFixed(1)} KB (SVG)</div>
                              </div>
                            ) : (
                              <span className="text-rose-600">No visual asset assigned</span>
                            )}
                          </div>

                          <div className="p-2 bg-slate-50 rounded border border-slate-100">
                            <span className="font-semibold text-slate-700 block mb-0.5">Narration Audio</span>
                            {scene.is_silent ? (
                              <span className="text-slate-500">Intentionally silent scene</span>
                            ) : scene.narration_asset ? (
                              <div>
                                <div className="text-slate-500 font-mono truncate">{scene.narration_asset.relative_path}</div>
                                <div className="text-slate-400 mt-0.5">
                                  {(scene.narration_asset.file_size_bytes / 1024).toFixed(1)} KB • {scene.narration_asset.duration_seconds?.toFixed(2)}s
                                </div>
                              </div>
                            ) : (
                              <span className="text-rose-600">Missing narration audio</span>
                            )}
                          </div>

                          <div className="p-2 bg-slate-50 rounded border border-slate-100">
                            <span className="font-semibold text-slate-700 block mb-0.5">Subtitles</span>
                            {scene.is_silent ? (
                              <span className="text-slate-500">None (silent scene)</span>
                            ) : scene.caption_srt_asset ? (
                              <div>
                                <div className="text-slate-500 font-mono truncate">{scene.caption_srt_asset.relative_path}</div>
                                <div className="text-slate-400 mt-0.5">{(scene.caption_srt_asset.file_size_bytes / 1024).toFixed(1)} KB (SRT)</div>
                              </div>
                            ) : (
                              <span className="text-rose-600">Missing subtitle assets</span>
                            )}
                          </div>
                        </div>

                        {scene.issues && scene.issues.length > 0 && (
                          <div className="p-2.5 bg-rose-50/70 border border-rose-100 rounded text-[11px] text-rose-700">
                            <span className="font-semibold block mb-1">Scene Issues:</span>
                            <ul className="list-disc pl-4 space-y-0.5">
                              {scene.issues.map((iss, i) => (
                                <li key={i}>{iss.message}</li>
                              ))}
                            </ul>
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
      ) : (
        /* Empty State */
        <div className="p-12 text-center">
          <div className="inline-flex p-3 bg-slate-100 text-slate-400 rounded-full mb-3">
            <FileCheck className="w-6 h-6" />
          </div>
          <h4 className="text-sm font-semibold text-slate-800">No Assembly Package Compiled</h4>
          <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
            Verify and package all visual assets, ElevenLabs narration audio, and synchronized captions before video compilation.
          </p>
          {!readOnly && (
            <button
              onClick={() => onValidate(false)}
              disabled={isLoading || !isStoryboardAvailable}
              className={`inline-flex items-center gap-2 px-4 py-2 text-xs font-medium rounded-lg shadow-sm transition-all ${
                isLoading || !isStoryboardAvailable
                  ? 'bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200'
                  : 'bg-indigo-600 hover:bg-indigo-700 text-white'
              }`}
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
              Validate Assembly Readiness
            </button>
          )}
        </div>
      )}
    </div>
  );
}
