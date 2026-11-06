import React, { useState } from 'react';
import {
  Mic,
  Volume2,
  Clock,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Play,
  Pause,
  AlertTriangle,
  Info,
  Radio,
  Sliders,
} from 'lucide-react';
import { getNarrationAudioUrl } from '../api/client';

export default function NarrationCard({
  jobId,
  narration,
  isLoading,
  onGenerate,
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

  const hasData = Boolean(narration && narration.assets && narration.assets.length > 0);
  const totalAssets = narration?.total_assets || 0;
  const completedAssets = (narration?.assets_completed || 0) + (narration?.assets_skipped || 0);
  const progressPercent = totalAssets > 0 ? Math.round((completedAssets / totalAssets) * 100) : 0;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-6 transition-all">
      {/* Card Header */}
      <div className="p-6 border-b border-slate-100 flex flex-wrap items-center justify-between gap-4 bg-slate-50/50">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-violet-100 text-violet-700 rounded-lg">
            <Mic className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-900 text-lg">Scene Narration Audio</h3>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-violet-50 text-violet-700 border border-violet-200">
                ElevenLabs TTS
              </span>
              {hasData && narration.status && (
                <span
                  className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                    narration.status === 'completed'
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                      : narration.status === 'failed'
                      ? 'bg-rose-50 text-rose-700 border border-rose-200'
                      : 'bg-amber-50 text-amber-700 border border-amber-200'
                  }`}
                >
                  {narration.status.toUpperCase()}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              High-fidelity voice synthesis synchronized with educational storyboard scenes
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {!readOnly && (
            <button
              onClick={() => onGenerate(Boolean(hasData))}
              disabled={isLoading || !isStoryboardAvailable}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                isLoading || !isStoryboardAvailable
                  ? 'bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200'
                  : hasData
                  ? 'bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 shadow-xs'
                  : 'bg-violet-600 hover:bg-violet-700 text-white shadow-xs'
              }`}
            >
              {isLoading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Synthesizing Audio...
                </>
              ) : hasData ? (
                <>
                  <RefreshCw className="w-4 h-4" />
                  Regenerate Audio
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  Generate Narration
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Prerequisite Missing Banner */}
      {!isStoryboardAvailable && !hasData && (
        <div className="p-6 text-center bg-slate-50/40">
          <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-3">
            <Clock className="w-6 h-6" />
          </div>
          <h4 className="text-sm font-semibold text-slate-800">Prerequisite Required</h4>
          <p className="text-xs text-slate-500 max-w-md mx-auto mt-1">
            Educational storyboard scenes must be generated before scene-by-scene narration audio can be synthesized.
          </p>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="p-4 bg-rose-50 border-b border-rose-100 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
          <div className="text-xs text-rose-800">
            <span className="font-semibold">Narration Generation Notice:</span> {error}
          </div>
        </div>
      )}

      {/* Loading Progress State */}
      {isLoading && (
        <div className="p-8 text-center bg-slate-50/30">
          <div className="inline-flex p-3 rounded-full bg-violet-50 text-violet-600 mb-3 animate-pulse">
            <Volume2 className="w-6 h-6" />
          </div>
          <h4 className="text-sm font-semibold text-slate-800">Synthesizing Spoken Audio</h4>
          <p className="text-xs text-slate-500 max-w-md mx-auto mt-1 mb-4">
            Calling ElevenLabs Text-to-Speech API to generate studio-quality scene narration.
          </p>
          <div className="w-64 h-2 bg-slate-100 rounded-full mx-auto overflow-hidden">
            <div className="h-full bg-violet-600 rounded-full animate-pulse" style={{ width: '70%' }} />
          </div>
        </div>
      )}

      {/* Rendered Narration Content */}
      {hasData && !isLoading && (
        <div className="p-6">
          {/* Summary Metric Stats Banner */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 rounded-xl bg-slate-50/80 border border-slate-100 mb-6">
            <div>
              <div className="text-xs text-slate-500 font-medium">Total Scenes</div>
              <div className="text-lg font-bold text-slate-900 mt-0.5">
                {narration.total_scenes}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500 font-medium">Synthesized</div>
              <div className="text-lg font-bold text-emerald-600 mt-0.5">
                {narration.scenes_completed}
                {narration.scenes_skipped > 0 && (
                  <span className="text-xs text-slate-400 font-normal ml-1">
                    (+{narration.scenes_skipped} skipped)
                  </span>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500 font-medium">Total Duration</div>
              <div className="text-lg font-bold text-violet-700 mt-0.5">
                {narration.sync_summary?.total_actual_duration_seconds ?? 0}s
                <span className="text-xs text-slate-400 font-normal ml-1">
                  (plan: {narration.sync_summary?.total_expected_duration_seconds ?? 0}s)
                </span>
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500 font-medium">Voice Model</div>
              <div className="text-xs font-semibold text-slate-700 truncate mt-1.5" title={narration.model_id}>
                {narration.model_id || 'eleven_multilingual_v2'}
              </div>
            </div>
          </div>

          {/* Timing Synchronization Warning Banner (if divergence detected) */}
          {narration.warnings && narration.warnings.length > 0 && (
            <div className="mb-6 p-4 rounded-lg bg-amber-50 border border-amber-200">
              <div className="flex items-center gap-2 text-xs font-semibold text-amber-800 mb-1">
                <AlertTriangle className="w-4 h-4 text-amber-600" />
                Audio Timing Notice for Video Assembly
              </div>
              <ul className="text-xs text-amber-700 list-disc list-inside space-y-0.5 pl-1">
                {narration.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Scene Narration Audio Asset List */}
          <div className="space-y-3">
            <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              Scene Audio Assets ({narration.assets.length})
            </h4>

            {narration.assets.map((asset, idx) => {
              const isExpanded = expandedScenes[idx] !== false; // default open
              const isCompleted = asset.status === 'completed';
              const isSkipped = asset.status === 'skipped';
              const isFailed = asset.status === 'failed';

              return (
                <div
                  key={asset.asset_id || idx}
                  className="rounded-lg border border-slate-200 overflow-hidden bg-white transition-all"
                >
                  {/* Scene Row Header */}
                  <div
                    onClick={() => toggleScene(idx)}
                    className="p-4 flex items-center justify-between gap-4 cursor-pointer hover:bg-slate-50/50"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-7 h-7 rounded-full bg-slate-100 flex items-center justify-center text-xs font-bold text-slate-700">
                        {asset.scene_number}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">
                            {`Scene ${asset.scene_number}`}
                          </span>
                          <span
                            className={`px-2 py-0.5 rounded text-[11px] font-medium ${
                              isCompleted
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                : isSkipped
                                ? 'bg-slate-100 text-slate-600 border border-slate-200'
                                : isFailed
                                ? 'bg-rose-50 text-rose-700 border border-rose-200'
                                : 'bg-amber-50 text-amber-700 border border-amber-200'
                            }`}
                          >
                            {asset.status.toUpperCase()}
                          </span>
                          {!asset.is_synchronized && isCompleted && (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                              TIMING SHIFT
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">
                          {isCompleted ? (
                            <span>
                              Spoken audio: <strong className="text-slate-800">{asset.duration_seconds}s</strong>{' '}
                              (planned: {asset.expected_scene_duration_seconds}s, diff:{' '}
                              <span className={asset.duration_difference_seconds > 0 ? 'text-amber-700' : 'text-slate-600'}>
                                {asset.duration_difference_seconds > 0 ? `+${asset.duration_difference_seconds}` : asset.duration_difference_seconds}s
                              </span>)
                            </span>
                          ) : isSkipped ? (
                            <span>No narration (visual only, {asset.expected_scene_duration_seconds}s)</span>
                          ) : (
                            <span>Estimated: {asset.expected_scene_duration_seconds}s</span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {isExpanded ? (
                        <ChevronUp className="w-4 h-4 text-slate-400" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-slate-400" />
                      )}
                    </div>
                  </div>

                  {/* Expanded Body */}
                  {isExpanded && (
                    <div className="p-4 pt-0 border-t border-slate-100 bg-slate-50/30 text-xs">
                      {/* Narration script text */}
                      {asset.narration_text ? (
                        <div className="mb-3 p-3 rounded-lg bg-white border border-slate-100 text-slate-700 italic">
                          "{asset.narration_text}"
                        </div>
                      ) : (
                        <div className="mb-3 text-slate-400 italic">No spoken narration for this scene.</div>
                      )}

                      {/* Audio Player if generated */}
                      {isCompleted && jobId && asset.asset_id && (
                        <div className="p-3 bg-white rounded-lg border border-slate-200 mb-2">
                          <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                            <Volume2 className="w-3.5 h-3.5 text-violet-600" />
                            Audio Preview ({asset.duration_seconds}s • {Math.round(asset.file_size_bytes / 1024)} KB)
                          </div>
                          <audio
                            key={`${jobId}-${asset.asset_id}`}
                            controls
                            src={getNarrationAudioUrl(jobId, asset.asset_id)}
                            preload="metadata"
                            className="w-full h-8"
                          />
                        </div>
                      )}

                      {/* Error details if failed */}
                      {asset.error_message && (
                        <div className="p-3 bg-rose-50 border border-rose-200 rounded text-rose-800 mt-2">
                          <span className="font-semibold">Error:</span> {asset.error_message}
                        </div>
                      )}

                      {/* Synchronization warning if divergent */}
                      {asset.sync_warning && !isSkipped && (
                        <div className="p-2.5 bg-amber-50 border border-amber-200 rounded text-amber-800 mt-2 flex items-center gap-2">
                          <Info className="w-3.5 h-3.5 shrink-0 text-amber-600" />
                          <span>{asset.sync_warning}</span>
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
  );
}
