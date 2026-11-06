import React, { useState, useEffect } from 'react';
import {
  Video,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
  Cpu,
  Sliders,
  Settings2,
  Monitor,
  Activity,
  Layers,
  Film,
  Play,
  Download,
  Clock,
  Volume2,
  VolumeX,
} from 'lucide-react';
import {
  getVideoSystemStatus,
  getSceneRenders,
  renderScenes,
  getSceneRenderFileUrl,
} from '../../api/client';

export default function VideoAssemblyCard({
  jobId,
  renderJob = null,
  sceneRenders = null,
  systemStatus = null,
  onRefresh = null,
  isLoading = false,
  readOnly = false,
}) {
  const [localStatus, setLocalStatus] = useState(systemStatus);
  const [fetchingStatus, setFetchingStatus] = useState(false);
  const [fetchError, setFetchError] = useState(null);

  // Scene rendering state
  const [sceneResult, setSceneResult] = useState(sceneRenders);
  const [renderingScenes, setRenderingScenes] = useState(false);
  const [sceneError, setSceneError] = useState(null);
  const [forceRefresh, setForceRefresh] = useState(false);

  useEffect(() => {
    if (systemStatus) {
      setLocalStatus(systemStatus);
    } else {
      loadStatus(false);
    }
  }, [systemStatus]);

  useEffect(() => {
    if (sceneRenders) {
      setSceneResult(sceneRenders);
    } else if (jobId) {
      loadSceneRenders();
    }
  }, [sceneRenders, jobId]);

  const loadStatus = async (force = false) => {
    setFetchingStatus(true);
    setFetchError(null);
    try {
      const res = await getVideoSystemStatus(force);
      if (res.success && res.data) {
        setLocalStatus(res.data);
      } else {
        setFetchError(res.error || 'Failed to query video assembly status');
      }
    } catch (err) {
      setFetchError(err.message || 'Error querying video assembly status');
    } finally {
      setFetchingStatus(false);
    }
  };

  const loadSceneRenders = async () => {
    try {
      const res = await getSceneRenders(jobId);
      if (res.success && res.data) {
        setSceneResult(res.data);
      }
    } catch {
      // Not yet generated
    }
  };

  const handleRenderScenes = async () => {
    if (renderingScenes || isLoading) return;
    setRenderingScenes(true);
    setSceneError(null);

    try {
      const res = await renderScenes(jobId, forceRefresh);
      if (res.success && res.data) {
        setSceneResult(res.data);
        if (onRefresh) onRefresh();
      } else {
        setSceneError(res.error || 'Failed to render scene clips');
      }
    } catch (err) {
      setSceneError(err.message || 'Unexpected error while rendering scenes');
    } finally {
      setRenderingScenes(false);
    }
  };

  const ffmpeg = localStatus?.ffmpeg;
  const ffprobe = localStatus?.ffprobe;
  const isReady = Boolean(localStatus?.is_ready);
  const config = renderJob?.configuration || localStatus?.default_configuration || {
    resolution_width: 1920,
    resolution_height: 1080,
    fps: 30,
    video_codec: 'libx264',
    audio_codec: 'aac',
    pixel_format: 'yuv420p',
    aspect_ratio: '16:9',
  };

  const totalScenes = sceneResult?.total_scenes || 0;
  const completedScenes = sceneResult?.completed_scenes || 0;
  const failedScenes = sceneResult?.failed_scenes || 0;
  const isComplete = Boolean(sceneResult?.is_complete);
  const scenesList = sceneResult?.scenes || [];

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm mb-6 transition-all">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 gap-3">
        <div className="flex items-center gap-3">
          <div className={`p-2.5 rounded-lg ${isReady ? 'bg-indigo-50 text-indigo-600' : 'bg-amber-50 text-amber-600'}`}>
            <Video className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-900 text-lg">Video Assembly & Scene Rendering</h3>
              <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-mono">
                Phase 6.2
              </span>
            </div>
            <p className="text-sm text-slate-500">
              Host media encoding environment, visual rasterization, and per-scene MP4 generation
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Status Badge */}
          {isReady ? (
            <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
              FFMPEG READY
            </span>
          ) : (
            <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
              BINARIES MISSING
            </span>
          )}

          {!readOnly && (
            <button
              onClick={() => {
                if (onRefresh) onRefresh();
                loadStatus(true);
                loadSceneRenders();
              }}
              disabled={fetchingStatus || renderingScenes || isLoading}
              className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50"
              title="Refresh status"
            >
              <RefreshCw className={`w-4 h-4 ${fetchingStatus ? 'animate-spin' : ''}`} />
            </button>
          )}
        </div>
      </div>

      {/* Error banner if fetching status failed */}
      {fetchError && (
        <div className="mt-4 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-sm flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-rose-600 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">System Inspection Warning</p>
            <p className="text-xs text-rose-700 mt-0.5">{fetchError}</p>
          </div>
        </div>
      )}

      {/* System Binaries Status Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-5">
        {/* FFmpeg Box */}
        <div className={`p-4 rounded-xl border ${ffmpeg?.is_available ? 'bg-slate-50/60 border-slate-200' : 'bg-amber-50/40 border-amber-200'}`}>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Cpu className={`w-4 h-4 ${ffmpeg?.is_available ? 'text-indigo-600' : 'text-amber-600'}`} />
              <span className="text-sm font-semibold text-slate-800">FFmpeg Encoder</span>
            </div>
            {ffmpeg?.is_available ? (
              <span className="text-xs font-medium text-emerald-700 bg-emerald-100/70 px-2 py-0.5 rounded">
                {`v${ffmpeg.version}`}
              </span>
            ) : (
              <span className="text-xs font-medium text-amber-700 bg-amber-100/80 px-2 py-0.5 rounded">
                Not Installed
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mb-2 font-mono truncate" title={ffmpeg?.executable_path || 'Not detected in PATH'}>
            {ffmpeg?.executable_path || 'Binary not found in system PATH'}
          </p>
          {!ffmpeg?.is_available && (
            <p className="text-xs text-amber-700 mt-1">
              {ffmpeg?.error || 'Install FFmpeg to enable hardware-accelerated video assembly and encoding.'}
            </p>
          )}
        </div>

        {/* FFprobe Box */}
        <div className={`p-4 rounded-xl border ${ffprobe?.is_available ? 'bg-slate-50/60 border-slate-200' : 'bg-amber-50/40 border-amber-200'}`}>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Activity className={`w-4 h-4 ${ffprobe?.is_available ? 'text-indigo-600' : 'text-amber-600'}`} />
              <span className="text-sm font-semibold text-slate-800">FFprobe Inspector</span>
            </div>
            {ffprobe?.is_available ? (
              <span className="text-xs font-medium text-emerald-700 bg-emerald-100/70 px-2 py-0.5 rounded">
                {`v${ffprobe.version}`}
              </span>
            ) : (
              <span className="text-xs font-medium text-amber-700 bg-amber-100/80 px-2 py-0.5 rounded">
                Not Installed
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mb-2 font-mono truncate" title={ffprobe?.executable_path || 'Not detected in PATH'}>
            {ffprobe?.executable_path || 'Binary not found in system PATH'}
          </p>
          {!ffprobe?.is_available && (
            <p className="text-xs text-amber-700 mt-1">
              {ffprobe?.error || 'Install FFprobe for media stream validation, sample rate analysis, and duration checks.'}
            </p>
          )}
        </div>
      </div>

      {/* Render Configuration Parameters */}
      <div className="mt-5 pt-4 border-t border-slate-100">
        <div className="flex items-center gap-2 mb-3">
          <Sliders className="w-4 h-4 text-slate-600" />
          <h4 className="text-xs font-bold text-slate-700 tracking-wider uppercase">Default Encoding Parameters</h4>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-200/60">
            <span className="text-slate-400 text-[11px] block uppercase font-medium">Resolution</span>
            <span className="text-slate-800 text-sm font-semibold font-mono">
              {`${config.resolution_width} × ${config.resolution_height}`}
            </span>
          </div>
          <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-200/60">
            <span className="text-slate-400 text-[11px] block uppercase font-medium">Framerate</span>
            <span className="text-slate-800 text-sm font-semibold font-mono">
              {`${config.fps} FPS`}
            </span>
          </div>
          <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-200/60">
            <span className="text-slate-400 text-[11px] block uppercase font-medium">Video Codec</span>
            <span className="text-slate-800 text-sm font-semibold font-mono">
              {`${config.video_codec} (${config.pixel_format})`}
            </span>
          </div>
          <div className="bg-slate-50 p-2.5 rounded-lg border border-slate-200/60">
            <span className="text-slate-400 text-[11px] block uppercase font-medium">Audio Codec</span>
            <span className="text-slate-800 text-sm font-semibold font-mono">
              {`${config.audio_codec} (${config.audio_sample_rate || 44100} Hz)`}
            </span>
          </div>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* Scene Rendering Section (Phase 6.2) */}
      {/* ==================================================================== */}
      <div className="mt-6 pt-5 border-t border-slate-100">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-3 gap-2">
          <div className="flex items-center gap-2">
            <Film className="w-4 h-4 text-indigo-600" />
            <h4 className="text-sm font-bold text-slate-800">Scene Video Segments (Phase 6.2)</h4>
            {isComplete ? (
              <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                ALL SCENES RENDERED
              </span>
            ) : completedScenes > 0 ? (
              <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                PARTIAL RENDER ({completedScenes}/{totalScenes})
              </span>
            ) : (
              <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-100 text-slate-600">
                NOT RENDERED
              </span>
            )}
          </div>

          {!readOnly && (
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-slate-500 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={forceRefresh}
                  onChange={(e) => setForceRefresh(e.target.checked)}
                  disabled={renderingScenes || isLoading}
                  className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                />
                Force Refresh
              </label>

              <button
                onClick={handleRenderScenes}
                disabled={renderingScenes || isLoading || !isReady}
                className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition-all flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {renderingScenes ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Rendering Scenes...
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-current" />
                    Render Scenes
                  </>
                )}
              </button>
            </div>
          )}
        </div>

        {/* Scene error banner */}
        {sceneError && (
          <div className="mt-2 mb-3 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">Scene Rendering Failed</p>
              <p className="mt-0.5">{sceneError}</p>
            </div>
          </div>
        )}

        {/* Scene Metrics */}
        {totalScenes > 0 && (
          <div className="grid grid-cols-3 gap-3 my-3">
            <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200/60 text-center">
              <span className="text-[11px] uppercase font-semibold text-slate-400 block">Total Scenes</span>
              <span className="text-base font-bold text-slate-800 font-mono">{totalScenes}</span>
            </div>
            <div className="p-2.5 rounded-lg bg-emerald-50/60 border border-emerald-200/60 text-center">
              <span className="text-[11px] uppercase font-semibold text-emerald-600 block">Rendered</span>
              <span className="text-base font-bold text-emerald-700 font-mono">{completedScenes}</span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-200/60 text-center">
              <span className="text-[11px] uppercase font-semibold text-slate-400 block">Failed</span>
              <span className={`text-base font-bold font-mono ${failedScenes > 0 ? 'text-rose-600' : 'text-slate-700'}`}>
                {failedScenes}
              </span>
            </div>
          </div>
        )}

        {/* Scenes List */}
        {scenesList.length > 0 ? (
          <div className="mt-3 space-y-2 max-h-60 overflow-y-auto pr-1">
            {scenesList.map((sc) => {
              const isClipCompleted = sc.status === 'completed';
              const isClipFailed = sc.status === 'failed';
              const fileUrl = getSceneRenderFileUrl(jobId, sc.scene_id);

              return (
                <div
                  key={sc.scene_id}
                  className="flex items-center justify-between p-2.5 rounded-lg border border-slate-200/70 bg-slate-50/40 hover:bg-slate-50 transition-colors text-xs"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="font-mono font-bold text-slate-500 bg-slate-200/70 px-1.5 py-0.5 rounded text-[11px] shrink-0">
                      {`#${sc.scene_number}`}
                    </span>
                    <div className="min-w-0">
                      <p className="font-medium text-slate-800 truncate" title={sc.title}>
                        {sc.title || `Scene ${sc.scene_number}`}
                      </p>
                      <div className="flex items-center gap-2 text-[11px] text-slate-500 mt-0.5">
                        <span className="flex items-center gap-1 font-mono">
                          <Clock className="w-3 h-3 text-slate-400" />
                          {sc.actual_duration_seconds ? `${sc.actual_duration_seconds.toFixed(1)}s` : `${sc.expected_duration_seconds.toFixed(1)}s`}
                        </span>
                        <span>•</span>
                        {sc.is_silent ? (
                          <span className="flex items-center gap-0.5 text-slate-500">
                            <VolumeX className="w-3 h-3 text-slate-400" /> Silent
                          </span>
                        ) : (
                          <span className="flex items-center gap-0.5 text-indigo-600">
                            <Volume2 className="w-3 h-3 text-indigo-500" /> Narrated
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {isClipCompleted && (
                      <>
                        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          READY
                        </span>
                        <a
                          href={fileUrl}
                          target="_blank"
                          rel="noreferrer"
                          download={`scene_${sc.scene_number}_${sc.scene_id}.mp4`}
                          className="p-1 text-slate-500 hover:text-indigo-600 hover:bg-slate-200/60 rounded transition-colors"
                          title="Download scene MP4 clip"
                        >
                          <Download className="w-3.5 h-3.5" />
                        </a>
                      </>
                    )}
                    {isClipFailed && (
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200" title={sc.error}>
                        FAILED
                      </span>
                    )}
                    {!isClipCompleted && !isClipFailed && (
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-100 text-slate-600">
                        {sc.status.toUpperCase()}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-slate-400 italic mt-2">
            {readOnly
              ? 'No scene clips rendered yet.'
              : 'No scene clips rendered yet. Click "Render Scenes" to generate individual MP4 clips.'}
          </p>
        )}
      </div>

      {/* Stage Status & Lifecycle Notice */}
      <div className="mt-5 p-3 bg-slate-50 border border-slate-200/80 rounded-lg text-xs text-slate-600 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-slate-500 shrink-0" />
          <span>Stage 09 (Video Rendering) status: <strong>{isComplete ? 'IN_PROGRESS (Scenes Ready)' : 'PENDING'}</strong> — Final video concatenation belongs to Phase 6.3+.</span>
        </div>
        <span className="text-[11px] px-2 py-0.5 rounded bg-slate-200/70 font-semibold text-slate-700">
          CONTAINER: {config.container_format?.toUpperCase() || 'MP4'}
        </span>
      </div>
    </div>
  );
}
