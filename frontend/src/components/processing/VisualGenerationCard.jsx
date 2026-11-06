import React, { useState } from 'react';
import { 
  Palette, 
  Sparkles, 
  CheckCircle2, 
  Clock, 
  AlertCircle, 
  RotateCcw, 
  Eye, 
  Layers, 
  Code2, 
  Network, 
  Layout, 
  Image as ImageIcon,
  ExternalLink,
  ChevronRight
} from 'lucide-react';
import { getVisualAssetFileUrl } from '../../api/client';

export default function VisualGenerationCard({
  jobId,
  visualGeneration,
  isLoading = false,
  error = null,
  onGenerate = () => {},
  readOnly = false,
  hasStoryboard = true,
}) {
  const [selectedAsset, setSelectedAsset] = useState(null);

  // If uninitialized
  if (!visualGeneration && !isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center font-bold">
              <Palette className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-slate-900">Stage 07: Visual Asset Generation</h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 font-medium border border-slate-200">
                  Pending
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                Generates high-definition technical diagrams, call flows, and scene cards.
              </p>
            </div>
          </div>

          {!readOnly && (
            <button
              onClick={() => onGenerate(false)}
              disabled={!hasStoryboard || isLoading}
              className={`px-4 py-2 rounded-xl text-xs font-medium flex items-center gap-1.5 shadow-sm transition ${
                hasStoryboard
                  ? 'bg-purple-600 hover:bg-purple-700 text-white'
                  : 'bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Generate Visuals</span>
            </button>
          )}
        </div>

        {!hasStoryboard && (
          <div className="mt-4 p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span>Prerequisite required: Educational Storyboard (Stage 06) must be generated first.</span>
          </div>
        )}

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-sm">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center font-bold animate-pulse">
            <Palette className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-900">Stage 07: Visual Asset Generation</h3>
              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-50 text-purple-600 font-medium border border-purple-200 flex items-center gap-1">
                <Clock className="w-3 h-3 animate-spin" /> In Progress
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Synthesizing SVG diagrams, code snapshots, and visual layouts...
            </p>
          </div>
        </div>
        <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
          <div className="bg-purple-600 h-2 rounded-full w-2/3 animate-pulse" />
        </div>
      </div>
    );
  }

  const scenes = visualGeneration?.assets || [];
  const totalScenes = visualGeneration?.total_scenes || scenes.length;
  const renderedScenes = visualGeneration?.rendered_scenes_count || scenes.filter(s => s.visual_assets?.some(a => a.status === 'rendered')).length;
  const isComplete = visualGeneration?.is_fully_rendered || visualGeneration?.status === 'completed';

  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center font-bold">
            <Palette className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-900">Stage 07: Visual Asset Generation</h3>
              {isComplete ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 font-semibold border border-emerald-200 flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" /> Completed
                </span>
              ) : (
                <span className="text-xs px-2 py-0.5 rounded-full bg-purple-50 text-purple-600 font-medium border border-purple-200">
                  Ready ({renderedScenes}/{totalScenes} Scenes)
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              1080p SVG visual blueprints tailored for technical comprehension.
            </p>
          </div>
        </div>

        {!readOnly && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => onGenerate(true)}
              className="px-3 py-1.5 rounded-xl border border-slate-200 hover:bg-slate-50 text-slate-600 text-xs font-medium flex items-center gap-1.5 transition"
              title="Force re-render all visual assets"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Regenerate</span>
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/80">
          <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Total Scenes</span>
          <p className="text-lg font-bold text-slate-800 mt-0.5">{totalScenes}</p>
        </div>
        <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/80">
          <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Rendered Visuals</span>
          <p className="text-lg font-bold text-purple-600 mt-0.5">{renderedScenes}</p>
        </div>
        <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/80">
          <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Format</span>
          <p className="text-lg font-bold text-slate-800 mt-0.5">1920x1080 SVG</p>
        </div>
        <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/80">
          <span className="text-[10px] uppercase font-semibold text-slate-400 tracking-wider">Blueprint Mode</span>
          <p className="text-lg font-bold text-emerald-600 mt-0.5">Verified Safe</p>
        </div>
      </div>

      {/* Scenes Gallery */}
      <div className="space-y-3">
        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 flex items-center gap-1.5">
          <Layers className="w-3.5 h-3.5 text-purple-600" />
          <span>Scene Visual Blueprint Gallery</span>
        </h4>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {scenes.map((scene) => {
            const primaryAsset = scene.visual_assets?.[0];
            const fileUrl = (jobId && primaryAsset) ? getVisualAssetFileUrl(jobId, primaryAsset.asset_id) : null;
            const isRendered = primaryAsset?.status === 'rendered';

            return (
              <div 
                key={scene.scene_id || scene.scene_number}
                className="p-4 rounded-xl border border-slate-200 bg-white hover:border-purple-300 transition shadow-sm space-y-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-200">
                      {`Scene #${scene.scene_number}`}
                    </span>
                    <span className="text-xs font-medium text-slate-600 truncate max-w-[180px]">
                      {scene.visual_type || 'Technical Diagram'}
                    </span>
                  </div>
                  {isRendered ? (
                    <span className="text-[11px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> Ready
                    </span>
                  ) : (
                    <span className="text-[11px] text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
                      Planned
                    </span>
                  )}
                </div>

                <p className="text-xs text-slate-600 line-clamp-2">
                  {scene.description || 'Visual diagram designed for pedagogical architecture clarity.'}
                </p>

                {/* Preview Thumbnail */}
                {fileUrl && isRendered ? (
                  <div className="relative group/preview rounded-lg overflow-hidden border border-slate-200 aspect-video bg-slate-900 flex items-center justify-center">
                    <img 
                      src={fileUrl} 
                      alt={`Scene ${scene.scene_number} visual preview`}
                      className="w-full h-full object-contain"
                      loading="lazy"
                    />
                    <a
                      href={fileUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="absolute inset-0 bg-slate-900/40 opacity-0 group-hover/preview:opacity-100 transition flex items-center justify-center text-white text-xs font-medium gap-1.5"
                    >
                      <Eye className="w-4 h-4" />
                      <span>View Full Resolution</span>
                    </a>
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center aspect-video flex flex-col items-center justify-center bg-slate-50 text-slate-400">
                    <ImageIcon className="w-6 h-6 mb-1 text-slate-300" />
                    <span className="text-[11px]">Visual card pending render</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
