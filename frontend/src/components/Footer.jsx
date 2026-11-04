import React from 'react';
import { Sparkles, Terminal, Code2, Film, ShieldCheck } from 'lucide-react';

export default function Footer() {
  return (
    <footer className="bg-white border-t border-slate-200 mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          <div className="md:col-span-2 space-y-3">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center text-white">
                <Sparkles className="w-4 h-4" />
              </div>
              <span className="font-bold text-slate-900 tracking-tight">RepoGenie</span>
            </div>
            <p className="text-sm text-slate-500 max-w-sm">
              Transforming complex GitHub repositories into comprehensive, synchronized educational videos using automated AST parsing, AI architecture reasoning, and FFmpeg video synthesis.
            </p>
            <div className="flex items-center gap-4 text-xs text-slate-400 pt-2">
              <span className="flex items-center gap-1"><Terminal className="w-3.5 h-3.5" /> Python FastAPI</span>
              <span>•</span>
              <span className="flex items-center gap-1"><Code2 className="w-3.5 h-3.5" /> React + Vite</span>
              <span>•</span>
              <span className="flex items-center gap-1"><Film className="w-3.5 h-3.5" /> FFmpeg Pipeline</span>
            </div>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-slate-900 uppercase tracking-wider mb-3">Pipeline Stages</h4>
            <ul className="text-xs space-y-2 text-slate-500">
              <li>1. Repository Ingestion</li>
              <li>2. AST & Tree-sitter Parsing</li>
              <li>3. AI Architecture Analysis</li>
              <li>4. Narration & Diagramming</li>
              <li>5. MP4 Video Compilation</li>
            </ul>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-slate-900 uppercase tracking-wider mb-3">Development Info</h4>
            <ul className="text-xs space-y-2 text-slate-500">
              <li>Milestone 1: Foundation</li>
              <li>Light-theme SaaS Interface</li>
              <li>Modular Microservice Ready</li>
              <li className="flex items-center gap-1 text-emerald-600">
                <ShieldCheck className="w-3.5 h-3.5" /> Safe Sandbox Execution
              </li>
            </ul>
          </div>
        </div>

        <div className="border-t border-slate-100 mt-8 pt-6 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-400 gap-4">
          <p>© {new Date().getFullYear()} RepoGenie. Built for developers, educators, and software engineers.</p>
          <p>Local Development Mode</p>
        </div>
      </div>
    </footer>
  );
}
