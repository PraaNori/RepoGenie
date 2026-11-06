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
} from 'lucide-react';
import { getVideoSystemStatus } from '../../api/client';

export default function VideoAssemblyCard({
  jobId,
  renderJob = null,
  systemStatus = null,
  onRefresh = null,
  isLoading = false,
  readOnly = false,
}) {
  const [localStatus, setLocalStatus] = useState(systemStatus);
  const [fetchingStatus, setFetchingStatus] = useState(false);
  const [fetchError, setFetchError] = useState(null);

  useEffect(() => {
    if (systemStatus) {
      setLocalStatus(systemStatus);
    } else {
      loadStatus(false);
    }
  }, [systemStatus]);

  const loadStatus = async (forceRefresh = false) => {
    setFetchingStatus(true);
    setFetchError(null);
    try {
      const res = await getVideoSystemStatus(forceRefresh);
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
              <h3 className="font-semibold text-slate-900 text-lg">Video Assembly Foundation</h3>
              <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-mono">
                Phase 6.1
              </span>
            </div>
            <p className="text-sm text-slate-500">
              Host media encoding environment, FFmpeg executable discovery, and render parameters
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
              }}
              disabled={fetchingStatus || isLoading}
              className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50"
              title="Refresh executable status"
            >
              <RefreshCw className={`w-4 h-4 ${fetchingStatus || isLoading ? 'animate-spin' : ''}`} />
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

      {/* Stage Status & Lifecycle Notice */}
      <div className="mt-4 p-3 bg-slate-50 border border-slate-200/80 rounded-lg text-xs text-slate-600 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-slate-500 shrink-0" />
          <span>Stage 09 (Video Rendering) status: <strong>PENDING</strong> — Full MP4 assembly will execute in Phase 6.2+.</span>
        </div>
        <span className="text-[11px] px-2 py-0.5 rounded bg-slate-200/70 font-semibold text-slate-700">
          CONTAINER: {config.container_format?.toUpperCase() || 'MP4'}
        </span>
      </div>
    </div>
  );
}
