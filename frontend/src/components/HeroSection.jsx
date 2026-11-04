import React from 'react';
import { Film, Code, Sparkles, Cpu, Layers } from 'lucide-react';
import UrlInputCard from './UrlInputCard';

export default function HeroSection({ onSubmitUrl, isSubmitting, backendOnline, serverError, onClearError }) {
  return (
    <section className="pt-12 sm:pt-16 pb-14 text-center">
      <div className="max-w-4xl mx-auto px-4 sm:px-6">
        {/* Badge */}
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-indigo-50 border border-indigo-100 text-indigo-700 text-xs font-medium mb-6">
          <Sparkles className="w-3.5 h-3.5" />
          <span>AI-Powered Code to Video Synthesis</span>
        </div>

        {/* Heading */}
        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-slate-900 tracking-tight leading-[1.15] mb-6">
          Turn Any GitHub Repository Into an{' '}
          <span className="bg-gradient-to-r from-indigo-600 via-violet-600 to-indigo-700 bg-clip-text text-transparent">
            Educational Video.
          </span>
        </h1>

        {/* Supporting description */}
        <p className="text-base sm:text-lg text-slate-600 max-w-2xl mx-auto mb-10 leading-relaxed">
          RepoGenie analyzes source code, architectural components, dependency graphs, and execution flows to automatically produce structured educational videos with narration, synchronized captions, and technical visualizations.
        </p>

        {/* Central URL Input Card */}
        <UrlInputCard 
          onSubmit={onSubmitUrl} 
          isSubmitting={isSubmitting} 
          backendOnline={backendOnline}
          serverError={serverError}
          onClearError={onClearError}
        />

        {/* Feature Pills */}
        <div className="mt-8 flex flex-wrap items-center justify-center gap-6 text-xs text-slate-500">
          <div className="flex items-center gap-1.5">
            <Code className="w-4 h-4 text-indigo-500" />
            <span>AST Code Analysis</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Layers className="w-4 h-4 text-indigo-500" />
            <span>Architecture Diagrams</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Cpu className="w-4 h-4 text-indigo-500" />
            <span>AI Storyboard Scripting</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Film className="w-4 h-4 text-indigo-500" />
            <span>Synchronized MP4 Output</span>
          </div>
        </div>
      </div>
    </section>
  );
}
