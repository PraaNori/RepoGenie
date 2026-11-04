import React, { useState } from 'react';
import { ArrowRight, Sparkles, AlertCircle, Check } from 'lucide-react';

function GithubIcon({ className = "w-5 h-5" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
    </svg>
  );
}

const SAMPLE_REPOS = [
  'https://github.com/fastapi/fastapi',
  'https://github.com/facebook/react',
  'https://github.com/pallets/flask',
  'https://github.com/expressjs/express',
];

export default function UrlInputCard({ onSubmit, isSubmitting, backendOnline, serverError, onClearError }) {
  const [url, setUrl] = useState('');
  const [validationError, setValidationError] = useState('');

  const validateUrl = (value) => {
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Please enter a GitHub repository URL.';
    }
    const regex = /^https?:\/\/(?:www\.)?github\.com\/[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+(?:\.git)?\/?(?:[?#].*)?$/;
    if (!regex.test(trimmed)) {
      return 'Please enter a valid public GitHub URL (e.g., https://github.com/owner/repository).';
    }
    return '';
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (isSubmitting) return;

    const error = validateUrl(url);
    if (error) {
      setValidationError(error);
      return;
    }
    setValidationError('');
    onSubmit(url.trim());
  };

  const handleSelectSample = (sampleUrl) => {
    if (isSubmitting) return;
    setUrl(sampleUrl);
    setValidationError('');
    if (onClearError) onClearError();
  };

  const handleInputChange = (e) => {
    setUrl(e.target.value);
    if (validationError) setValidationError('');
    if (onClearError) onClearError();
  };

  const displayError = validationError || serverError;

  return (
    <div className="w-full max-w-3xl mx-auto">
      <div className="bg-white rounded-2xl shadow-xl shadow-slate-200/50 border border-slate-200/80 p-4 sm:p-6 md:p-8 transition-all">
        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block text-sm font-semibold text-slate-800">
            Submit Public Repository
          </label>

          <div className="relative flex flex-col sm:flex-row items-stretch gap-2.5">
            <div className="relative flex-1">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                <GithubIcon className="w-5 h-5" />
              </div>
              <input
                type="text"
                value={url}
                onChange={handleInputChange}
                disabled={isSubmitting}
                placeholder="https://github.com/owner/repository"
                className={`w-full pl-11 pr-4 py-3.5 rounded-xl text-slate-900 bg-slate-50/70 border placeholder:text-slate-400 text-sm font-mono focus:bg-white focus:outline-none focus:ring-2 transition-all disabled:opacity-60 disabled:cursor-not-allowed ${
                  displayError
                    ? 'border-rose-300 focus:ring-rose-200 focus:border-rose-400'
                    : 'border-slate-200 focus:ring-indigo-200 focus:border-indigo-500'
                }`}
              />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm shadow-sm hover:shadow transition-all disabled:opacity-60 disabled:cursor-not-allowed group whitespace-nowrap"
            >
              {isSubmitting ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Ingesting Repository...</span>
                </>
              ) : (
                <>
                  <span>Generate Video</span>
                  <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                </>
              )}
            </button>
          </div>

          {displayError && (
            <div className="flex items-center gap-2 text-xs text-rose-600 bg-rose-50 border border-rose-100 p-3 rounded-lg text-left">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{displayError}</span>
            </div>
          )}

          {!backendOnline && (
            <div className="flex items-center gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 p-2.5 rounded-lg text-left">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>
                Backend is currently offline. Ensure FastAPI is running on port 8000.
              </span>
            </div>
          )}

          {/* Sample quick select */}
          <div className="pt-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-400 font-medium">Try an example:</span>
              {SAMPLE_REPOS.map((sample) => (
                <button
                  key={sample}
                  type="button"
                  disabled={isSubmitting}
                  onClick={() => handleSelectSample(sample)}
                  className="text-xs px-2.5 py-1 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-600 font-mono transition-colors disabled:opacity-50"
                >
                  {sample.replace('https://github.com/', '')}
                </button>
              ))}
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
