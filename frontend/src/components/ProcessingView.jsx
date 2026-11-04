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
  RotateCcw,
  FileCode,
  FolderTree,
  Box,
  Settings2,
  Layers,
  Cpu,
  Hash,
  Terminal
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
  const isStageTwoInProgress = job.stages?.[1]?.status === 'in_progress';
  const isStageThreeInProgress = job.stages?.[2]?.status === 'in_progress';
  const analysis = job.analysis;
  const codeAnalysis = job.code_analysis;

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 sm:px-6">
      {/* Error notification banner if failed */}
      {isFailed && (
        <div className="mb-6 p-4 sm:p-5 rounded-2xl bg-rose-50 border border-rose-200 text-rose-900 shadow-sm flex flex-col sm:flex-row items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="text-sm font-bold text-rose-900">Ingestion or Analysis Error</h4>
              <p className="text-xs text-rose-700 mt-1 leading-relaxed">
                {job.error || 'The repository processing could not be completed.'}
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
            <div className="flex items-center gap-2 mb-1 flex-wrap">
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
              {isStageTwoInProgress && (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-700 bg-violet-50 border border-violet-200 px-2 py-0.5 rounded-full">
                  <Loader2 className="w-3 h-3 animate-spin" /> Analyzing Structure & Languages
                </span>
              )}
              {isStageThreeInProgress && (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
                  <Loader2 className="w-3 h-3 animate-spin" /> Parsing Source Code AST
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
                disabled={isSimulating || isStageOneInProgress || isStageTwoInProgress || isStageThreeInProgress}
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
                {isFailed ? 'Processing Failed' : job.current_stage}
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

      {/* Milestone 2.3: Repository Analysis Summary Card */}
      {analysis && (
        <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-6 sm:p-8 mb-6 transition-all">
          <div className="flex items-center justify-between pb-4 border-b border-slate-100 mb-5">
            <div>
              <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
                <Search className="w-4 h-4 text-indigo-600" />
                <span>Repository Structure & Language Analysis</span>
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Static inspection of directory hierarchy, source files, and configuration files.
              </p>
            </div>
            <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-semibold">
              Analysis Verified
            </span>
          </div>

          {/* Statistics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <FileCode className="w-3.5 h-3.5 text-indigo-600" />
                <span>Source Files</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {analysis.statistics.source_files.toLocaleString()}
              </p>
              <span className="text-[11px] text-slate-400">
                of {analysis.statistics.total_files.toLocaleString()} total files
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <FolderTree className="w-3.5 h-3.5 text-indigo-600" />
                <span>Directories</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {analysis.statistics.total_directories.toLocaleString()}
              </p>
              <span className="text-[11px] text-slate-400">traversed hierarchy</span>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <Box className="w-3.5 h-3.5 text-indigo-600" />
                <span>Dependency Files</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {analysis.statistics.dependency_manifests}
              </p>
              <span className="text-[11px] text-slate-400">package manifests</span>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <Settings2 className="w-3.5 h-3.5 text-indigo-600" />
                <span>Config Files</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {analysis.statistics.configuration_files}
              </p>
              <span className="text-[11px] text-slate-400">Docker, CI/CD, tools</span>
            </div>
          </div>

          {/* Detected Languages */}
          <div className="mb-5">
            <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2.5">
              Detected Languages ({analysis.languages.length})
            </h4>
            <div className="flex flex-wrap gap-2">
              {analysis.languages.map((lang) => (
                <div
                  key={lang.name}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-indigo-50 border border-indigo-100 text-xs text-indigo-900"
                >
                  <span className="font-semibold">{lang.name}</span>
                  <span className="text-indigo-500 font-mono text-[11px]">{lang.percentage}%</span>
                  <span className="text-[10px] text-indigo-400 font-mono">({lang.file_count})</span>
                </div>
              ))}
            </div>
          </div>

          {/* Manifests and Config Highlights */}
          {analysis.dependency_files.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2">
                Manifest & Configuration Signals
              </h4>
              <div className="flex flex-wrap gap-2">
                {analysis.dependency_files.map((dep) => (
                  <span
                    key={dep.file_path}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-100 border border-slate-200 text-slate-700 text-xs font-mono"
                  >
                    <Box className="w-3 h-3 text-slate-500" />
                    <span>{dep.file_path}</span>
                    <span className="text-slate-400">({dep.dependencies_count} deps)</span>
                  </span>
                ))}
                {analysis.configuration_files.slice(0, 5).map((cfg) => (
                  <span
                    key={cfg.file_path}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-slate-50 border border-slate-200 text-slate-600 text-xs font-mono"
                  >
                    <Settings2 className="w-3 h-3 text-slate-400" />
                    <span>{cfg.file_path}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Warnings if any limit was reached */}
          {analysis.warnings.length > 0 && (
            <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-xs space-y-1">
              {analysis.warnings.map((w, idx) => (
                <div key={idx} className="flex items-center gap-1.5">
                  <AlertCircle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0" />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Milestone 2.4: Code Structure Analysis Summary Card */}
      {codeAnalysis && (
        <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-6 sm:p-8 mb-6 transition-all">
          <div className="flex items-center justify-between pb-4 border-b border-slate-100 mb-5">
            <div>
              <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
                <Code2 className="w-4 h-4 text-indigo-600" />
                <span>Code Structure & AST Analysis</span>
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Syntactic extraction via Tree-sitter: functions, classes, methods, imports, and calls.
              </p>
            </div>
            <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-semibold">
              AST Extracted
            </span>
          </div>

          {/* Statistics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3 mb-6">
            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <FileCode className="w-3.5 h-3.5 text-indigo-600" />
                <span>Files</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {codeAnalysis.total_parsed_files.toLocaleString()}
              </p>
              <span className="text-[10px] text-slate-400">parsed ASTs</span>
            </div>

            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <Terminal className="w-3.5 h-3.5 text-indigo-600" />
                <span>Functions</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {codeAnalysis.total_functions.toLocaleString()}
              </p>
              <span className="text-[10px] text-slate-400">top-level / async</span>
            </div>

            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <Layers className="w-3.5 h-3.5 text-indigo-600" />
                <span>Classes</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {codeAnalysis.total_classes.toLocaleString()}
              </p>
              <span className="text-[10px] text-slate-400">structs / ifaces</span>
            </div>

            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <Cpu className="w-3.5 h-3.5 text-indigo-600" />
                <span>Methods</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {codeAnalysis.total_methods.toLocaleString()}
              </p>
              <span className="text-[10px] text-slate-400">class members</span>
            </div>

            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <Box className="w-3.5 h-3.5 text-indigo-600" />
                <span>Imports</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {codeAnalysis.total_imports.toLocaleString()}
              </p>
              <span className="text-[10px] text-slate-400">modules / symbols</span>
            </div>

            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/70">
              <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                <Hash className="w-3.5 h-3.5 text-indigo-600" />
                <span>Calls</span>
              </div>
              <p className="text-lg font-bold text-slate-900 font-mono">
                {codeAnalysis.total_function_calls.toLocaleString()}
              </p>
              <span className="text-[10px] text-slate-400">call expressions</span>
            </div>
          </div>

          {/* Parsed Languages Badges */}
          <div className="mb-2">
            <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2.5">
              Parsed Languages ({codeAnalysis.supported_languages.length})
            </h4>
            <div className="flex flex-wrap gap-2">
              {codeAnalysis.supported_languages.map((lang) => (
                <span
                  key={lang}
                  className="px-2.5 py-1 rounded-md bg-indigo-50 text-indigo-800 border border-indigo-200/80 text-xs font-medium font-mono"
                >
                  {lang}
                </span>
              ))}
            </div>
          </div>

          {/* Warnings if any parsing limits or issues occurred */}
          {codeAnalysis.warnings && codeAnalysis.warnings.length > 0 && (
            <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-xs space-y-1">
              {codeAnalysis.warnings.map((w, idx) => (
                <div key={idx} className="flex items-center gap-1.5">
                  <AlertCircle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0" />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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
