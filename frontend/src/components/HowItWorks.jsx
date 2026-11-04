import React from 'react';
import { GitBranch, BrainCircuit, Clapperboard, Film, Database, Network, FileCode2, CheckCircle2 } from 'lucide-react';

const STEPS = [
  {
    step: '01',
    title: 'Repository Ingestion & Parsing',
    description: 'Fetches codebases, inspects folder hierarchy, extracts dependencies, and parses AST structures using Tree-sitter.',
    icon: GitBranch,
  },
  {
    step: '02',
    title: 'Architecture & Flow Understanding',
    description: 'Identifies core modules, entry points, APIs, database schemas, and data flow from verified code artifacts.',
    icon: BrainCircuit,
  },
  {
    step: '03',
    title: 'Educational Script & Storyboard',
    description: 'Generates a pedagogical explanation, breaking down technical concepts into structured visual scenes.',
    icon: Clapperboard,
  },
  {
    step: '04',
    title: 'Audio, Visuals & MP4 Assembly',
    description: 'Synthesizes code visualizations, architecture graphs, voice narration, captions, and renders full MP4 via FFmpeg.',
    icon: Film,
  },
];

const CAPABILITIES = [
  {
    title: 'Project Overview & Tech Stack',
    desc: 'Extracts languages, backend/frontend frameworks, external services, and deployment configurations.',
    icon: FileCode2,
  },
  {
    title: 'Architectural Hierarchy',
    desc: 'Maps major components, controllers, business logic layers, and relational interactions.',
    icon: Network,
  },
  {
    title: 'Database & Data Models',
    desc: 'Understands tables, collections, schemas, relationships, and CRUD operations.',
    icon: Database,
  },
  {
    title: 'Ground-Truth Verification',
    desc: 'Extracts information directly from actual source code. Never hallucinates non-existent libraries or endpoints.',
    icon: CheckCircle2,
  },
];

export default function HowItWorks() {
  return (
    <section className="py-16 bg-white border-y border-slate-200/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-14">
          <h2 className="text-xs font-bold uppercase tracking-wider text-indigo-600 mb-2">How RepoGenie Works</h2>
          <h3 className="text-3xl font-bold text-slate-900 tracking-tight">
            From Git Commits to Studio-Quality Educational Videos
          </h3>
          <p className="mt-3 text-slate-600 text-sm">
            A deterministic, multi-stage engineering pipeline designed to make software architectures effortlessly understandable.
          </p>
        </div>

        {/* 4 Steps */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-16">
          {STEPS.map((item) => {
            const Icon = item.icon;
            return (
              <div
                key={item.step}
                className="relative p-6 rounded-2xl bg-slate-50/60 border border-slate-200/70 hover:border-indigo-200 hover:bg-white hover:shadow-md transition-all group"
              >
                <div className="text-xs font-mono font-bold text-indigo-600 mb-4 flex items-center justify-between">
                  <span>STAGE {item.step}</span>
                  <div className="w-8 h-8 rounded-lg bg-indigo-100/60 group-hover:bg-indigo-600 group-hover:text-white text-indigo-700 flex items-center justify-center transition-colors">
                    <Icon className="w-4 h-4" />
                  </div>
                </div>
                <h4 className="text-base font-semibold text-slate-900 mb-2">{item.title}</h4>
                <p className="text-xs text-slate-600 leading-relaxed">{item.description}</p>
              </div>
            );
          })}
        </div>

        {/* Capabilities Grid */}
        <div className="bg-slate-50 rounded-2xl p-6 sm:p-8 border border-slate-200">
          <div className="mb-6">
            <h4 className="text-lg font-bold text-slate-900">Extracted Repository Knowledge</h4>
            <p className="text-xs text-slate-500 mt-1">
              RepoGenie is built for engineering rigor — extracting actual code artifacts rather than vague summaries.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {CAPABILITIES.map((cap) => {
              const Icon = cap.icon;
              return (
                <div key={cap.title} className="p-4 rounded-xl bg-white border border-slate-200/80">
                  <div className="w-7 h-7 rounded-md bg-indigo-50 text-indigo-600 flex items-center justify-center mb-3">
                    <Icon className="w-4 h-4" />
                  </div>
                  <h5 className="text-sm font-semibold text-slate-900 mb-1">{cap.title}</h5>
                  <p className="text-xs text-slate-500 leading-relaxed">{cap.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
