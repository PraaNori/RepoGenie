import React from 'react';
import { 
  GitBranch, 
  Search, 
  Code2, 
  Sparkles, 
  FileText, 
  Clapperboard, 
  Palette, 
  Volume2, 
  Film, 
  CheckCircle2, 
  Clock, 
  Loader2, 
  AlertCircle,
  ArrowRight,
  ExternalLink,
  ChevronRight,
  RotateCcw
} from 'lucide-react';

const STAGE_ICONS = {
  'Repository Fetching': GitBranch,
  'Repository Analysis': Search,
  'Code Understanding': Code2,
  'AI Summary Generation': Sparkles,
  'Script Generation': FileText,
  'Storyboard Generation': Clapperboard,
  'Visual Generation': Palette,
  'Voice Generation': Volume2,
  'Video Assembly': Film,
};

export default function ProcessingView({ 
  job, 
  onSimulateStep, 
  isSimulating, 
  onViewResults,
  onCancel
}) {
  if (!job) {
    return (
      <div className="max-w-3xl mx-auto py-16 text-center">
        <div className="bg-white rounded-2xl border border-slate-200 p-8 shadow-sm">
          <AlertCircle className="w-8 h-8 text-amber-500 mx-auto mb-3" />
          <h3 className="text-lg font-bold text-slate-800">No active job</h3>
          <p className="text-sm text-slate-500 mt-1 mb-6">
            Submit a GitHub repository from the homepage or load a sample job.
          </p>
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition"
          >
            Go to Homepage
          </button>
        </div>
      </div>
    );
  }

  const isCompleted = job.status === 'completed' || job.progress_percentage === 100;
  const isFailed = job.status === 'failed';
  const isStageOneInProgress = job.stages?.[0]?.status === 'in_progress';

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 sm:px-6">
      {/* Error notification banner if failed */}
      {isFailed && (
        <div className="mb-6 p-4 sm:p-5 rounded-2xl bg-rose-50 border border-rose-200 text-rose-900 shadow-sm flex flex-col sm:flex-row items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-bold text-rose-900">Ingestion Error Encountered</h4>
              <p className="text-xs text-rose-700 mt-1 leading-relaxed">
                {job.error || 'The repository could not be ingested. Verify that the repository is public and accessible.'}
              </p>
            </div>
          </div>
          <button
            onClick={onCancel}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold shadow-sm transition whitespace-nowrap self-end sm:self-center"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Try Another URL</span>
          </button>
        </div>
      )}

      {/* Header Card */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-6 sm:p-8 mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-100">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
                Pipeline Processing
              </span>
              <span className="text-xs text-slate-400">•</span>
              <span className="text-xs font-mono text-slate-500">ID: {job.job_id?.slice(0, 8)}...</span>
              {isStageOneInProgress && (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-indigo-700 bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded-full">
                  <Loader2 className="w-3 h-3 animate-spin" /> Ingesting Git Repository
                </span>
              )}
            </div>
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
              <span>{job.repo_name}</span>
              <a 
                href={job.repo_url} 
                target="_blank" 
                rel="noreferrer" 
                className="text-slate-400 hover:text-slate-700 transition-colors"
                title="Open GitHub repository"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            </h2>
            <p className="text-xs font-mono text-slate-500 mt-0.5 truncate max-w-md">
              {job.repo_url}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {isCompleted ? (
              <button
                onClick={onViewResults}
                className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-sm transition"
              >
                <span>View Generated Video</span>
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : !isFailed && (
              <button
                onClick={onSimulateStep}
                disabled={isSimulating || isStageOneInProgress}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200/70 text-xs font-semibold transition disabled:opacity-50"
                title="Advance to next stage"
              >
                {isSimulating ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <ArrowRight className="w-3.5 h-3.5" />
                )}
                <span>Simulate Next Stage</span>
              </button>
            )}

            <button
              onClick={onCancel}
              className="px-3 py-2 rounded-xl border border-slate-200 text-slate-600 hover:text-slate-900 text-xs font-medium hover:bg-slate-50 transition"
            >
              Back
            </button>
          </div>
        </div>

        {/* Progress Bar & Current Status */}
        <div className="pt-6">
          <div className="flex items-center justify-between text-xs font-semibold mb-2">
            <span className="text-slate-700 flex items-center gap-2">
              <span className="text-slate-400">Current Stage:</span>
              <span className={`font-bold ${isFailed ? 'text-rose-600' : 'text-indigo-600'}`}>
                {isFailed ? 'Ingestion Failed' : job.current_stage}
              </span>
            </span>
            <span className="text-slate-900 font-mono text-sm">{job.progress_percentage}%</span>
          </div>

          <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
            <div
              className={`h-2.5 rounded-full transition-all duration-500 ${
                isFailed
                  ? 'bg-rose-500'
                  : isCompleted
                  ? 'bg-emerald-500'
                  : 'bg-gradient-to-r from-indigo-500 to-violet-600'
              }`}
              style={{ width: `${Math.max(5, job.progress_percentage)}%` }}
            />
          </div>
        </div>
      </div>

      {/* 9 Stages List */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-6 sm:p-8">
        <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider mb-4">
          Pipeline Execution Breakdown (9 Stages)
        </h3>

        <div className="space-y-3">
          {job.stages?.map((stage, index) => {
            const Icon = STAGE_ICONS[stage.name] || Code2;
            const isStageCompleted = stage.status === 'completed';
            const isStageInProgress = stage.status === 'in_progress';
            const isStageFailed = stage.status === 'failed';
            const isStagePending = stage.status === 'pending';

            return (
              <div
                key={stage.id || stage.name}
                className={`p-3.5 rounded-xl border transition-all flex items-center justify-between ${
                  isStageFailed
                    ? 'border-rose-300 bg-rose-50/50 shadow-sm ring-1 ring-rose-200'
                    : isStageInProgress
                    ? 'border-indigo-300 bg-indigo-50/50 shadow-sm ring-1 ring-indigo-200'
                    : isStageCompleted
                    ? 'border-emerald-200/60 bg-emerald-50/20'
                    : 'border-slate-100 bg-slate-50/50 opacity-75'
                }`}
              >
                <div className="flex items-center gap-3.5">
                  <div
                    className={`w-9 h-9 rounded-lg flex items-center justify-center text-sm font-semibold ${
                      isStageFailed
                        ? 'bg-rose-100 text-rose-700'
                        : isStageCompleted
                        ? 'bg-emerald-100 text-emerald-700'
                        : isStageInProgress
                        ? 'bg-indigo-600 text-white'
                        : 'bg-slate-200 text-slate-500'
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                  </div>

                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-slate-400">0{index + 1}</span>
                      <h4 className="text-sm font-semibold text-slate-900">{stage.name}</h4>
                    </div>
                    <p className={`text-xs mt-0.5 ${isStageFailed ? 'text-rose-600 font-medium' : 'text-slate-500'}`}>
                      {stage.detail || (
                        isStageCompleted
                          ? 'Done'
                          : isStageInProgress
                          ? 'Processing...'
                          : isStageFailed
                          ? 'Failed'
                          : 'Waiting in queue'
                      )}
                    </p>
                  </div>
                </div>

                <div>
                  {isStageCompleted && (
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-200">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Completed</span>
                    </span>
                  )}
                  {isStageInProgress && (
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-700 bg-indigo-100/70 px-2.5 py-1 rounded-full border border-indigo-200">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>In Progress</span>
                    </span>
                  )}
                  {isStageFailed && (
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-rose-700 bg-rose-100 px-2.5 py-1 rounded-full border border-rose-200">
                      <AlertCircle className="w-3.5 h-3.5" />
                      <span>Failed</span>
                    </span>
                  )}
                  {isStagePending && (
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-400 bg-slate-100 px-2.5 py-1 rounded-full">
                      <Clock className="w-3.5 h-3.5" />
                      <span>Pending</span>
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
