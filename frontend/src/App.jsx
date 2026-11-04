import React, { useState, useEffect, useCallback } from 'react';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import HeroSection from './components/HeroSection';
import HowItWorks from './components/HowItWorks';
import ProcessingView from './components/ProcessingView';
import VideoResultView from './components/VideoResultView';
import { checkBackendHealth, createJob, getJobStatus, simulateJobStep } from './api/client';

export default function App() {
  const [currentView, setCurrentView] = useState('home'); // 'home' | 'processing' | 'result'
  const [backendStatus, setBackendStatus] = useState({ connected: false, info: null, error: null });
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [currentJob, setCurrentJob] = useState(null);
  const [serverError, setServerError] = useState('');

  // Health check handler
  const checkHealth = useCallback(async () => {
    setIsCheckingHealth(true);
    const result = await checkBackendHealth();
    if (result.success) {
      setBackendStatus({ connected: true, info: result.data, error: null });
    } else {
      setBackendStatus({ connected: false, info: null, error: result.error });
    }
    setIsCheckingHealth(false);
  }, []);

  // Check health on initial mount
  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  // Polling for live ingestion progress
  useEffect(() => {
    if (
      currentView !== 'processing' ||
      !currentJob ||
      !backendStatus.connected ||
      currentJob.job_id.startsWith('mock-')
    ) {
      return;
    }

    const isProcessing =
      currentJob.ingestion_status === 'in_progress' ||
      currentJob.stages?.[0]?.status === 'in_progress' ||
      currentJob.stages?.[1]?.status === 'in_progress' ||
      currentJob.stages?.[2]?.status === 'in_progress';

    if (!isProcessing) {
      return;
    }

    const timer = setInterval(async () => {
      const res = await getJobStatus(currentJob.job_id);
      if (res.success) {
        setCurrentJob(res.data);
      }
    }, 1200);

    return () => clearInterval(timer);
  }, [currentView, currentJob, backendStatus.connected]);

  // Handle URL submission from Homepage
  const handleSubmitUrl = async (githubUrl) => {
    setServerError('');
    setIsSubmitting(true);

    if (backendStatus.connected) {
      const res = await createJob(githubUrl);
      if (res.success) {
        setCurrentJob(res.data);
        setCurrentView('processing');
      } else {
        setServerError(res.error);
      }
      setIsSubmitting(false);
      return;
    }

    // Backend is offline, provide mock demo job
    const repoName = githubUrl.replace(/^https?:\/\/(?:www\.)?github\.com\//, '').replace(/\/$/, '');
    const mockJob = {
      job_id: 'mock-m2-' + Date.now(),
      repo_name: repoName,
      repo_url: githubUrl,
      status: 'pending',
      current_stage: 'Repository Fetching',
      progress_percentage: 0,
      ingestion_status: 'pending',
      stages: [
        { id: 1, name: 'Repository Fetching', status: 'pending', detail: 'Ready to fetch repository' },
        { id: 2, name: 'Repository Analysis', status: 'pending', detail: 'Waiting in queue' },
        { id: 3, name: 'Code Understanding', status: 'pending', detail: 'Waiting in queue' },
        { id: 4, name: 'AI Summary Generation', status: 'pending', detail: 'Waiting in queue' },
        { id: 5, name: 'Script Generation', status: 'pending', detail: 'Waiting in queue' },
        { id: 6, name: 'Storyboard Generation', status: 'pending', detail: 'Waiting in queue' },
        { id: 7, name: 'Visual Generation', status: 'pending', detail: 'Waiting in queue' },
        { id: 8, name: 'Voice Generation', status: 'pending', detail: 'Waiting in queue' },
        { id: 9, name: 'Video Assembly', status: 'pending', detail: 'Waiting in queue' },
      ],
    };
    setCurrentJob(mockJob);
    setCurrentView('processing');
    setIsSubmitting(false);
  };

  // Advance simulation step for remaining stages
  const handleSimulateStep = async () => {
    if (!currentJob) return;

    setIsSimulating(true);

    // If job exists on backend, advance it via API
    if (backendStatus.connected && !currentJob.job_id.startsWith('mock-')) {
      const res = await simulateJobStep(currentJob.job_id);
      if (res.success) {
        setCurrentJob(res.data);
        if (res.data.status === 'completed') {
          setTimeout(() => setCurrentView('result'), 900);
        }
      } else {
        alert(`Simulation error: ${res.error}`);
      }
    } else {
      // Local fallback simulation
      const stages = [...currentJob.stages];
      const targetIdx = stages.findIndex((s) => s.status !== 'completed');
      if (targetIdx !== -1) {
        if (stages[targetIdx].status === 'pending') {
          stages[targetIdx].status = 'in_progress';
          stages[targetIdx].detail = `Processing ${stages[targetIdx].name}...`;
        } else if (stages[targetIdx].status === 'in_progress') {
          stages[targetIdx].status = 'completed';
          stages[targetIdx].detail = `Finished ${stages[targetIdx].name} successfully.`;
          if (targetIdx + 1 < stages.length) {
            stages[targetIdx + 1].status = 'in_progress';
            stages[targetIdx + 1].detail = `Processing ${stages[targetIdx + 1].name}...`;
          }
        }
      }

      const completedCount = stages.filter((s) => s.status === 'completed').length;
      const progress = Math.min(100, Math.round((completedCount / stages.length) * 100));
      const isAllDone = completedCount === stages.length;

      const updated = {
        ...currentJob,
        stages,
        progress_percentage: progress,
        status: isAllDone ? 'completed' : 'in_progress',
        current_stage: isAllDone ? 'All stages completed' : stages.find(s => s.status === 'in_progress')?.name || stages[0].name,
        result: isAllDone ? {
          repo_name: currentJob.repo_name,
          repo_url: currentJob.repo_url,
          description: `Comprehensive educational walkthrough for ${currentJob.repo_name}.`,
          tech_stack: ['Python', 'FastAPI', 'React', 'Tailwind CSS', 'Vite'],
          summary: `Deconstructs ${currentJob.repo_name} architecture, file dependencies, and core operational lifecycle into clear educational scenes.`,
          video_url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
          duration_seconds: 180,
        } : null,
      };

      setCurrentJob(updated);
      if (isAllDone) {
        setTimeout(() => setCurrentView('result'), 900);
      }
    }

    setIsSimulating(false);
  };

  const handleReset = () => {
    setCurrentJob(null);
    setServerError('');
    setCurrentView('home');
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900">
      <Navbar
        currentView={currentView}
        onSelectView={setCurrentView}
        backendStatus={backendStatus}
        onRefreshHealth={checkHealth}
        isCheckingHealth={isCheckingHealth}
      />

      <main className="flex-1">
        {currentView === 'home' && (
          <div>
            <HeroSection
              onSubmitUrl={handleSubmitUrl}
              isSubmitting={isSubmitting}
              backendOnline={backendStatus.connected}
              serverError={serverError}
              onClearError={() => setServerError('')}
            />
            <HowItWorks />
          </div>
        )}

        {currentView === 'processing' && (
          <ProcessingView
            job={currentJob}
            onSimulateStep={handleSimulateStep}
            isSimulating={isSimulating}
            onViewResults={() => setCurrentView('result')}
            onCancel={handleReset}
            onJobUpdated={(updatedJob) => setCurrentJob(updatedJob)}
          />
        )}

        {currentView === 'result' && (
          <VideoResultView
            job={currentJob}
            onReset={handleReset}
          />
        )}
      </main>

      <Footer />
    </div>
  );
}
