import React, { useState, useEffect } from 'react';
import WorkflowUnderstandingCard from './WorkflowUnderstandingCard';
import { getWorkflowUnderstanding } from '../api/client';
import { 
  Download, 
  RotateCcw, 
  ExternalLink, 
  Play, 
  Pause, 
  Film, 
  Code, 
  CheckCircle2, 
  Sparkles,
  Layers,
  FileCode,
  Workflow,
  AlertCircle
} from 'lucide-react';

export default function VideoResultView({ job, onReset }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [workflowUnderstanding, setWorkflowUnderstanding] = useState(job?.workflow_understanding || null);
  const [workflowError, setWorkflowError] = useState(null);

  useEffect(() => {
    let isMounted = true;
    if (job?.job_id && (job?.has_workflow_understanding || job?.workflow_understanding) && !workflowUnderstanding) {
      if (job.workflow_understanding) {
        setWorkflowUnderstanding(job.workflow_understanding);
      } else {
        getWorkflowUnderstanding(job.job_id)
          .then((res) => {
            if (!isMounted) return;
            if (res.success) {
              setWorkflowUnderstanding(res.data);
              setWorkflowError(null);
            } else if (res.status === 404) {
              // HTTP 404 indicates an absent optional workflow analysis; treat cleanly as absent
              setWorkflowUnderstanding(null);
              setWorkflowError(null);
            } else {
              // Unexpected server or network error: record for non-intrusive alert
              setWorkflowUnderstanding(null);
              setWorkflowError(res.error || 'Failed to load optional workflow analysis');
            }
          })
          .catch((err) => {
            if (isMounted) {
              setWorkflowUnderstanding(null);
              setWorkflowError(err.message || 'Unexpected error loading optional workflow analysis');
            }
          });
      }
    }
    return () => {
      isMounted = false;
    };
  }, [job?.job_id, job?.has_workflow_understanding, job?.workflow_understanding, workflowUnderstanding]);

  // Fallback data if viewing directly without active job
  const repoName = job?.repo_name || 'fastapi/fastapi';
  const repoUrl = job?.repo_url || 'https://github.com/fastapi/fastapi';
  const description = job?.result?.description || 'FastAPI framework, high performance, easy to learn, fast to code, ready for production.';
  const techStack = job?.result?.tech_stack || ['Python', 'Starlette', 'Pydantic', 'Uvicorn', 'OpenAPI'];
  const summary = job?.result?.summary || 'This video walks through the Starlette routing core, dependency injection system, Pydantic data validation model, and automatic OpenAPI documentation generation.';
  const videoUrl = job?.result?.video_url || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4';

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 sm:px-6">
      {/* Top Banner / Breadcrumb */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
              <CheckCircle2 className="w-3.5 h-3.5" /> Video Ready
            </span>
            <span className="text-xs text-slate-400">•</span>
            <span className="text-xs text-slate-500">1080p MP4 H.264</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <span>{repoName}</span>
            <a 
              href={repoUrl} 
              target="_blank" 
              rel="noreferrer" 
              className="text-slate-400 hover:text-slate-700 transition"
              title="Open GitHub"
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          </h2>
        </div>

        <div className="flex items-center gap-3">
          <a
            href={videoUrl}
            download={`${repoName.replace('/', '-')}-educational-video.mp4`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-xs sm:text-sm shadow-sm transition"
          >
            <Download className="w-4 h-4" />
            <span>Download MP4</span>
          </a>

          <button
            onClick={onReset}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-slate-200 hover:bg-slate-100 text-slate-700 font-medium text-xs sm:text-sm transition"
          >
            <RotateCcw className="w-4 h-4" />
            <span>Generate Another Video</span>
          </button>
        </div>
      </div>

      {/* Main Grid: Video Player + Repo Details */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Video Player */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-slate-900 rounded-2xl overflow-hidden shadow-lg border border-slate-800 aspect-video relative group flex items-center justify-center">
            <video
              className="w-full h-full object-cover"
              controls
              playsInline
              preload="metadata"
              poster="https://images.unsplash.com/photo-1555066931-4365d14bab8c?q=80&w=1200&auto=format&fit=crop"
              src={videoUrl}
            >
              Your browser does not support video playback.
            </video>
          </div>

          <div className="p-4 rounded-xl bg-white border border-slate-200/80 shadow-sm flex items-center justify-between text-xs text-slate-500">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5 font-medium text-slate-700">
                <Film className="w-3.5 h-3.5 text-indigo-600" />
                <span>Format: 1920x1080 (30fps)</span>
              </span>
              <span>•</span>
              <span>Audio: English Narration (Synchronized)</span>
            </div>
            <span className="font-mono text-slate-400">Duration: 03:00</span>
          </div>
        </div>

        {/* Right 1 Col: Repository Intelligence Metadata */}
        <div className="space-y-6">
          {/* Tech Stack Card */}
          <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-3 flex items-center gap-1.5">
              <Code className="w-3.5 h-3.5 text-indigo-600" />
              <span>Technology Stack</span>
            </h4>
            <div className="flex flex-wrap gap-2">
              {techStack.map((tech) => (
                <span
                  key={tech}
                  className="px-2.5 py-1 rounded-lg bg-indigo-50 border border-indigo-100 text-indigo-700 text-xs font-mono font-medium"
                >
                  {tech}
                </span>
              ))}
            </div>
          </div>

          {/* Project Description Card */}
          <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-2 flex items-center gap-1.5">
              <FileCode className="w-3.5 h-3.5 text-indigo-600" />
              <span>Project Description</span>
            </h4>
            <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">
              {description}
            </p>
          </div>

          {/* Repository Summary Card */}
          <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-2 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-indigo-600" />
              <span>Video Breakdown & Architecture</span>
            </h4>
            <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">
              {summary}
            </p>
          </div>
        </div>
      </div>

      {/* Discovered Application Workflows & Data Flows (Milestone 3.5.2) */}
      {workflowUnderstanding && (
        <div className="mt-8 pt-6 border-t border-slate-200">
          <WorkflowUnderstandingCard
            workflowUnderstanding={workflowUnderstanding}
            readOnly
          />
        </div>
      )}

      {/* Non-intrusive notification for unexpected optional workflow load failures */}
      {workflowError && (
        <div className="mt-8 pt-6 border-t border-slate-200">
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-600 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0" />
              <span>Optional workflow analysis could not be retrieved: {workflowError}</span>
            </div>
            <button
              onClick={() => setWorkflowError(null)}
              className="text-slate-400 hover:text-slate-600 font-medium transition"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
