import React, { useState } from 'react';
import {
  Subtitles,
  FileText,
  Clock,
  Download,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  Info,
  Layers,
  Sparkles,
} from 'lucide-react';
import { getCaptionFileUrl } from '../../api/client';

export default function CaptionsCard({
  jobId,
  captions,
  isLoading,
  onGenerate,
  error,
  isNarrationAvailable = false,
  readOnly = false,
}) {
  const [expandedScenes, setExpandedScenes] = useState({});

  const toggleScene = (idx) => {
    setExpandedScenes((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  const hasData = Boolean(captions && captions.scene_assets && captions.scene_assets.length > 0);
  const totalScenes = captions?.total_scenes || 0;
  const completedScenes = (captions?.scenes_completed || 0) + (captions?.scenes_skipped || 0);
  const progressPercent = totalScenes > 0 ? Math.round((completedScenes / totalScenes) * 100) : 0;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-6 transition-all">
      {/* Card Header */}
      <div className="p-6 border-b border-slate-100 flex flex-wrap items-center justify-between gap-4 bg-slate-50/50">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-blue-100 text-blue-700 rounded-lg">
            <Subtitles className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-900 text-lg">Subtitles & Captions</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                SRT & WebVTT
              </span>
              {hasData && captions.status && (
                <span
                  className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                    captions.status === 'completed'
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                      : captions.status === 'failed'
                      ? 'bg-rose-50 text-rose-700 border border-rose-200'
                      : 'bg-amber-50 text-amber-700 border border-amber-200'
                  }`}
                >
                  {captions.status.toUpperCase()}
                </span>
              )}
            </div>
            <p className="text-sm text-slate-500 mt-0.5">
              Deterministic, phrase-segmented subtitles timed to measured narration audio
            </p>
          </div>
        </div>

        {/* Action Button */}
        {!readOnly && (
          <div className="flex items-center gap-3">
            <button
              onClick={() => onGenerate(hasData)}
              disabled={isLoading || !isNarrationAvailable}
              className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg shadow-sm transition-all ${
                isLoading || !isNarrationAvailable
                  ? 'bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200'
                  : hasData
                  ? 'bg-white hover:bg-slate-50 text-slate-700 border border-slate-300 hover:border-slate-400'
                  : 'bg-blue-600 hover:bg-blue-700 text-white shadow-blue-500/20'
              }`}
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              {isLoading
                ? 'Generating Subtitles...'
                : hasData
                ? 'Regenerate Captions'
                : 'Generate Captions'}
            </button>
          </div>
        )}
      </div>

      {/* Progress Bar (During Generation) */}
      {isLoading && (
        <div className="w-full bg-slate-100 h-1.5 overflow-hidden">
          <div
            className="bg-blue-600 h-full transition-all duration-300 ease-out animate-pulse"
            style={{ width: `${Math.max(progressPercent, 20)}%` }}
          />
        </div>
      )}

      {/* Card Body */}
      <div className="p-6">
        {/* Error Banner */}
        {error && (
          <div className="mb-6 p-4 bg-rose-50 border border-rose-200 rounded-lg flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-semibold text-rose-900">Caption Generation Error</h4>
              <p className="text-sm text-rose-700 mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* Prerequisite Missing State */}
        {!hasData && !isLoading && !isNarrationAvailable && (
          <div className="p-8 text-center bg-slate-50 rounded-xl border border-dashed border-slate-200">
            <div className="w-12 h-12 bg-slate-100 text-slate-400 rounded-full flex items-center justify-center mx-auto mb-3">
              <Clock className="w-6 h-6" />
            </div>
            <h4 className="text-base font-semibold text-slate-800">Narration Audio Required</h4>
            <p className="text-sm text-slate-500 max-w-md mx-auto mt-1 mb-2">
              Generate scene narration audio in Stage 08 before generating synchronized subtitles.
            </p>
          </div>
        )}

        {/* Ready to Generate State */}
        {!hasData && !isLoading && isNarrationAvailable && !error && (
          <div className="p-8 text-center bg-slate-50 rounded-xl border border-dashed border-slate-200">
            <div className="w-12 h-12 bg-blue-50 text-blue-600 rounded-full flex items-center justify-center mx-auto mb-3">
              <Sparkles className="w-6 h-6" />
            </div>
            <h4 className="text-base font-semibold text-slate-800">Ready to Generate Subtitles</h4>
            <p className="text-sm text-slate-500 max-w-md mx-auto mt-1 mb-5">
              Produce proportional, natural-reading SRT and WebVTT captions using the completed scene narration assets.
            </p>
            {!readOnly && (
              <button
                onClick={() => onGenerate(false)}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm rounded-lg shadow-sm transition-all"
              >
                <Subtitles className="w-4 h-4" />
                Generate Subtitles
              </button>
            )}
          </div>
        )}

        {/* Loading State Spinner */}
        {isLoading && (
          <div className="p-12 text-center">
            <div className="inline-block p-4 bg-blue-50 text-blue-600 rounded-full animate-bounce mb-4">
              <Subtitles className="w-8 h-8" />
            </div>
            <h4 className="text-base font-semibold text-slate-800">Generating Captions...</h4>
            <p className="text-sm text-slate-500 mt-1 max-w-sm mx-auto">
              Segmenting narration text into natural phrases and calculating proportional timing from audio assets.
            </p>
          </div>
        )}

        {/* Completed State: Subtitle Metadata & Cues */}
        {hasData && (
          <div className="space-y-6">
            {/* Overview Metric Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 bg-slate-50 rounded-lg border border-slate-200/80">
                <span className="text-xs font-medium text-slate-500 uppercase tracking-wider block">
                  Scenes Processed
                </span>
                <span className="text-2xl font-bold text-slate-900 mt-1 block">
                  {`${captions.scenes_completed} / ${captions.total_scenes}`}
                </span>
                <span className="text-xs text-slate-500 mt-0.5 block">
                  {captions.scenes_skipped > 0 ? `${captions.scenes_skipped} silent scenes skipped` : '100% narrated'}
                </span>
              </div>

              <div className="p-4 bg-slate-50 rounded-lg border border-slate-200/80">
                <span className="text-xs font-medium text-slate-500 uppercase tracking-wider block">
                  Total Caption Cues
                </span>
                <span className="text-2xl font-bold text-slate-900 mt-1 block">
                  {captions.total_captions}
                </span>
                <span className="text-xs text-slate-500 mt-0.5 block">
                  ~{(captions.total_duration_seconds || 0).toFixed(1)}s total duration
                </span>
              </div>

              <div className="p-4 bg-slate-50 rounded-lg border border-slate-200/80">
                <span className="text-xs font-medium text-slate-500 uppercase tracking-wider block">
                  Timing Provenance
                </span>
                <div className="flex items-center gap-1.5 mt-1.5">
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-blue-100 text-blue-800">
                    {captions.timing_provenance === 'aligned' ? 'Verified Alignment' : 'Estimated Proportional'}
                  </span>
                </div>
                <span className="text-xs text-slate-500 mt-1 block">
                  Punctuation-weighted cues
                </span>
              </div>

              <div className="p-4 bg-slate-50 rounded-lg border border-slate-200/80">
                <span className="text-xs font-medium text-slate-500 uppercase tracking-wider block">
                  Full Video Subtitles
                </span>
                <div className="flex items-center gap-2 mt-1.5">
                  <a
                    href={getCaptionFileUrl(jobId, 'full', 'srt')}
                    target="_blank"
                    rel="noreferrer"
                    download={`job_${jobId}_captions.srt`}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded shadow-sm transition-all"
                  >
                    <Download className="w-3 h-3 text-slate-500" />
                    .SRT
                  </a>
                  <a
                    href={getCaptionFileUrl(jobId, 'full', 'vtt')}
                    target="_blank"
                    rel="noreferrer"
                    download={`job_${jobId}_captions.vtt`}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-white hover:bg-slate-100 text-slate-700 border border-slate-300 rounded shadow-sm transition-all"
                  >
                    <Download className="w-3 h-3 text-slate-500" />
                    .VTT
                  </a>
                </div>
                <span className="text-xs text-slate-500 mt-1 block">
                  Composite video track
                </span>
              </div>
            </div>

            {/* Warnings Banner if any */}
            {captions.warnings && captions.warnings.length > 0 && (
              <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg">
                <div className="flex items-center gap-2 text-amber-800 font-medium text-xs">
                  <AlertTriangle className="w-4 h-4 text-amber-600" />
                  <span>Subtitle Timing Warnings</span>
                </div>
                <ul className="mt-1.5 space-y-1 list-disc list-inside text-xs text-amber-700">
                  {captions.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Scene-by-Scene Subtitle Accordion */}
            <div className="border border-slate-200 rounded-lg divide-y divide-slate-100 overflow-hidden">
              <div className="px-4 py-2.5 bg-slate-100/60 flex items-center justify-between text-xs font-medium text-slate-600">
                <span>SCENE SUBTITLE BREAKDOWN</span>
                <span>{`${captions.scene_assets.length} SCENES`}</span>
              </div>

              {captions.scene_assets.map((sceneAsset, idx) => {
                const isExpanded = Boolean(expandedScenes[idx]);
                const cueCount = sceneAsset.captions?.length || 0;
                const isSkipped = sceneAsset.status === 'skipped';
                const isFailed = sceneAsset.status === 'failed';

                return (
                  <div key={sceneAsset.asset_id} className="bg-white">
                    <button
                      onClick={() => toggleScene(idx)}
                      className="w-full px-4 py-3 text-left flex items-center justify-between hover:bg-slate-50 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <span className="w-6 h-6 rounded-full bg-slate-100 text-slate-700 text-xs font-semibold flex items-center justify-center shrink-0">
                          {sceneAsset.scene_number}
                        </span>
                        <div>
                          <span className="text-sm font-medium text-slate-800">
                            {`Scene ${sceneAsset.scene_number}`}
                          </span>
                          <span className="text-xs text-slate-500 ml-2">
                            {isSkipped
                              ? '(Silent scene - no subtitles)'
                              : isFailed
                              ? '(Failed to generate)'
                              : `${cueCount} cues • ${(sceneAsset.duration_seconds || 0).toFixed(1)}s`}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {!isSkipped && !isFailed && (
                          <div className="flex items-center gap-1.5 mr-2" onClick={(e) => e.stopPropagation()}>
                            <a
                              href={getCaptionFileUrl(jobId, sceneAsset.asset_id, 'srt')}
                              target="_blank"
                              rel="noreferrer"
                              download={`${sceneAsset.asset_id}.srt`}
                              className="px-2 py-0.5 text-xs text-slate-600 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded"
                            >
                              SRT
                            </a>
                            <a
                              href={getCaptionFileUrl(jobId, sceneAsset.asset_id, 'vtt')}
                              target="_blank"
                              rel="noreferrer"
                              download={`${sceneAsset.asset_id}.vtt`}
                              className="px-2 py-0.5 text-xs text-slate-600 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded"
                            >
                              VTT
                            </a>
                          </div>
                        )}
                        {isExpanded ? (
                          <ChevronUp className="w-4 h-4 text-slate-400" />
                        ) : (
                          <ChevronDown className="w-4 h-4 text-slate-400" />
                        )}
                      </div>
                    </button>

                    {/* Expanded Cues Detail */}
                    {isExpanded && (
                      <div className="px-4 pb-4 pt-1 bg-slate-50/50 border-t border-slate-100">
                        {isSkipped ? (
                          <p className="text-xs text-slate-500 italic py-2">
                            This scene has no spoken narration. Subtitles are skipped.
                          </p>
                        ) : isFailed ? (
                          <p className="text-xs text-rose-600 italic py-2">
                            {sceneAsset.error_message || 'Subtitle generation failed for this scene.'}
                          </p>
                        ) : cueCount === 0 ? (
                          <p className="text-xs text-slate-500 italic py-2">No subtitle cues available.</p>
                        ) : (
                          <div className="space-y-2 mt-2">
                            {sceneAsset.captions.map((cue) => (
                              <div
                                key={cue.caption_id}
                                className="p-2.5 bg-white rounded border border-slate-200/80 flex items-start justify-between gap-3 text-xs"
                              >
                                <div className="space-y-1">
                                  <div className="font-mono text-blue-700 text-[11px] font-semibold">
                                    {cue.start_timestamp_srt} &rarr; {cue.end_timestamp_srt}
                                  </div>
                                  <div className="text-slate-800 font-medium">{cue.text}</div>
                                </div>
                                <span className="text-[10px] text-slate-400 font-mono shrink-0">
                                  # {cue.sequence_number}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
