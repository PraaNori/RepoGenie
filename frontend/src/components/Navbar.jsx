import React from 'react';
import { Sparkles, Activity, CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react';

export default function Navbar({ currentView, onSelectView, backendStatus, onRefreshHealth, isCheckingHealth }) {
  return (
    <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <div 
          onClick={() => onSelectView('home')} 
          className="flex items-center gap-3 cursor-pointer group"
        >
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center text-white shadow-sm group-hover:shadow transition-all">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg text-slate-900 tracking-tight">RepoGenie</span>
              <span className="text-[10px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200/60">
                Milestone 1
              </span>
            </div>
            <p className="text-xs text-slate-500 hidden sm:block">Repo to Educational Video</p>
          </div>
        </div>

        {/* View switcher & backend indicator */}
        <div className="flex items-center gap-2 sm:gap-4">
          {/* View switcher tabs for easy milestone evaluation */}
          <div className="hidden md:flex items-center p-1 bg-slate-100 rounded-lg text-xs font-medium text-slate-600">
            <button
              onClick={() => onSelectView('home')}
              className={`px-3 py-1.5 rounded-md transition-all ${
                currentView === 'home'
                  ? 'bg-white text-slate-900 shadow-sm font-semibold'
                  : 'hover:text-slate-900'
              }`}
            >
              Homepage
            </button>
            <button
              onClick={() => onSelectView('processing')}
              className={`px-3 py-1.5 rounded-md transition-all ${
                currentView === 'processing'
                  ? 'bg-white text-slate-900 shadow-sm font-semibold'
                  : 'hover:text-slate-900'
              }`}
            >
              Processing View
            </button>
            <button
              onClick={() => onSelectView('result')}
              className={`px-3 py-1.5 rounded-md transition-all ${
                currentView === 'result'
                  ? 'bg-white text-slate-900 shadow-sm font-semibold'
                  : 'hover:text-slate-900'
              }`}
            >
              Video Result View
            </button>
          </div>

          {/* Backend Health Badge */}
          <div className="flex items-center gap-2">
            {backendStatus.connected ? (
              <div 
                className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium"
                title={`Backend: ${backendStatus.info?.app_name} (${backendStatus.info?.version})`}
              >
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="hidden sm:inline">Backend</span> Connected
              </div>
            ) : (
              <div 
                className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700 text-xs font-medium"
                title={backendStatus.error || 'Backend not reachable'}
              >
                <span className="w-2 h-2 rounded-full bg-amber-500" />
                <span className="hidden sm:inline">Backend</span> Offline
              </div>
            )}

            <button
              onClick={onRefreshHealth}
              disabled={isCheckingHealth}
              className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600 hover:text-slate-900 transition-colors disabled:opacity-50"
              title="Refresh backend health status"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isCheckingHealth ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
