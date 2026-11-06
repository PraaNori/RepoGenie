/**
 * Milestone 5, Phase 5.4 Frontend Narration Unit Test Suite
 * Tests NarrationCard, VideoResultView, ProcessingView, API client methods,
 * audio playback rendering, timing synchronization alerts, and secret safety.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';

// Start Vite SSR server to dynamically load and transform JSX components
const vite = await createServer({
  server: { middlewareMode: true, hmr: false, ws: false },
  appType: 'custom',
});

const { default: NarrationCard } = await vite.ssrLoadModule(
  './src/components/NarrationCard.jsx'
);
const { default: VideoResultView } = await vite.ssrLoadModule(
  './src/components/VideoResultView.jsx'
);
const { default: ProcessingView } = await vite.ssrLoadModule(
  './src/components/ProcessingView.jsx'
);
const apiClient = await vite.ssrLoadModule('./src/api/client.js');

// Mock data fixtures conforming to NarrationGenerationResult schema
const mockNarrationData = {
  schema_version: '1.0',
  job_id: 'job-test-narration',
  status: 'completed',
  total_scenes: 3,
  scenes_completed: 2,
  scenes_skipped: 1,
  scenes_failed: 0,
  total_assets: 3,
  assets_completed: 2,
  assets_skipped: 1,
  assets_failed: 0,
  voice_id: 'Xb7hH8MSUJpSbSDYk0k2',
  model_id: 'eleven_multilingual_v2',
  sync_summary: {
    total_expected_duration_seconds: 30.0,
    total_actual_duration_seconds: 28.5,
    total_difference_seconds: -1.5,
    scenes_synchronized: 2,
    scenes_with_divergence: 0,
    scene_reports: [],
    synchronization_warnings: [],
  },
  warnings: [],
  assets: [
    {
      asset_id: 'audio_scene_1_intro',
      job_id: 'job-test-narration',
      scene_id: 'scene-1',
      scene_number: 1,
      script_section_id: 'sec-1',
      status: 'completed',
      file_path: 'jobs/job-test-narration/audio/audio_scene_1_intro.mp3',
      format: 'mp3',
      file_size_bytes: 48120,
      duration_seconds: 10.2,
      expected_scene_duration_seconds: 10.0,
      duration_difference_seconds: 0.2,
      is_synchronized: true,
      sync_warning: null,
      voice_id: 'Xb7hH8MSUJpSbSDYk0k2',
      model_id: 'eleven_multilingual_v2',
      narration_text: 'Welcome to this architectural walkthrough of Click.',
    },
    {
      asset_id: 'audio_scene_2_arch',
      job_id: 'job-test-narration',
      scene_id: 'scene-2',
      scene_number: 2,
      script_section_id: 'sec-2',
      status: 'completed',
      file_path: 'jobs/job-test-narration/audio/audio_scene_2_arch.mp3',
      format: 'mp3',
      file_size_bytes: 85200,
      duration_seconds: 18.3,
      expected_scene_duration_seconds: 15.0,
      duration_difference_seconds: 3.3,
      is_synchronized: false,
      sync_warning: 'Audio duration (18.3s) is longer than planned scene duration (15.0s) by +3.3s.',
      voice_id: 'Xb7hH8MSUJpSbSDYk0k2',
      model_id: 'eleven_multilingual_v2',
      narration_text: 'Click organizes command execution around Context objects.',
    },
    {
      asset_id: 'audio_scene_3_silent',
      job_id: 'job-test-narration',
      scene_id: 'scene-3',
      scene_number: 3,
      script_section_id: 'sec-3',
      status: 'skipped',
      file_path: null,
      format: 'mp3',
      file_size_bytes: 0,
      duration_seconds: 0.0,
      expected_scene_duration_seconds: 5.0,
      duration_difference_seconds: -5.0,
      is_synchronized: true,
      sync_warning: 'No narration text provided for scene; audio generation skipped.',
      voice_id: 'Xb7hH8MSUJpSbSDYk0k2',
      model_id: 'eleven_multilingual_v2',
      narration_text: '',
    },
  ],
};

test('1. NarrationCard renders "ready to generate" state when storyboard is available', () => {
  const html = renderToString(
    React.createElement(NarrationCard, {
      jobId: 'job-1',
      narration: null,
      isLoading: false,
      isStoryboardAvailable: true,
      onGenerate: () => {},
    })
  );

  assert.match(html, /Scene Narration Audio/);
  assert.match(html, /ElevenLabs TTS/);
  assert.match(html, /Generate Narration/);
  assert.doesNotMatch(html, /Prerequisite Required/);
});

test('2. NarrationCard indicates when prerequisite storyboard is not ready', () => {
  const html = renderToString(
    React.createElement(NarrationCard, {
      jobId: 'job-1',
      narration: null,
      isLoading: false,
      isStoryboardAvailable: false,
      onGenerate: () => {},
    })
  );

  assert.match(html, /Prerequisite Required/);
  assert.match(html, /Educational storyboard scenes must be generated/);
});

test('3. NarrationCard renders loading state with spinner', () => {
  const html = renderToString(
    React.createElement(NarrationCard, {
      jobId: 'job-1',
      narration: null,
      isLoading: true,
      isStoryboardAvailable: true,
      onGenerate: () => {},
    })
  );

  assert.match(html, /Synthesizing Spoken Audio/);
  assert.match(html, /Calling ElevenLabs Text-to-Speech API/);
});

test('4. NarrationCard displays error state cleanly', () => {
  const html = renderToString(
    React.createElement(NarrationCard, {
      jobId: 'job-1',
      narration: null,
      isLoading: false,
      isStoryboardAvailable: true,
      error: 'ElevenLabs rate limit exceeded. Please retry shortly.',
      onGenerate: () => {},
    })
  );

  assert.match(html, /Narration Generation Notice:/);
  assert.match(html, /ElevenLabs rate limit exceeded/);
});

test('5. NarrationCard renders generated narration scenes, stats, and audio player', () => {
  const html = renderToString(
    React.createElement(NarrationCard, {
      jobId: 'job-test-narration',
      narration: mockNarrationData,
      isLoading: false,
      isStoryboardAvailable: true,
      onGenerate: () => {},
    })
  );

  assert.match(html, /Scene Narration Audio/);
  assert.match(html, /COMPLETED/);
  assert.match(html, /eleven_multilingual_v2/);
  assert.match(html, /Scene 1/);
  assert.match(html, /Scene 2/);
  assert.match(html, /Scene 3/);
  assert.match(html, /SKIPPED/);
  assert.match(html, /TIMING SHIFT/);
  assert.match(html, /<audio/);
  assert.match(html, /api\/v1\/jobs\/job-test-narration\/narration\/audio_scene_1_intro\/file/);
});

test('6. NarrationCard hides regenerate button in readOnly mode', () => {
  const html = renderToString(
    React.createElement(NarrationCard, {
      jobId: 'job-test-narration',
      narration: mockNarrationData,
      isLoading: false,
      isStoryboardAvailable: true,
      readOnly: true,
      onGenerate: () => {},
    })
  );

  assert.doesNotMatch(html, /Regenerate Audio/);
  assert.doesNotMatch(html, /Generate Narration/);
  assert.match(html, /Scene 1/);
});

test('7. API client getNarrationAudioUrl formats URL correctly', () => {
  const url = apiClient.getNarrationAudioUrl('job-123', 'audio_scene_4');
  assert.match(url, /\/api\/v1\/jobs\/job-123\/narration\/audio_scene_4\/file/);
});

test('8. VideoResultView displays cached narration audio in readOnly mode', () => {
  const mockJob = {
    job_id: 'job-vr-test',
    repo_name: 'pallets/click',
    repo_url: 'https://github.com/pallets/click',
    has_narration: true,
    narration: mockNarrationData,
  };

  const html = renderToString(
    React.createElement(VideoResultView, {
      job: mockJob,
      onReset: () => {},
    })
  );

  assert.match(html, /Scene Narration Audio/);
  assert.match(html, /ElevenLabs TTS/);
});

test('9. Secret safety: ElevenLabs API keys are never rendered in frontend markup', () => {
  const html = renderToString(
    React.createElement(NarrationCard, {
      jobId: 'job-test-narration',
      narration: mockNarrationData,
      isLoading: false,
      isStoryboardAvailable: true,
      onGenerate: () => {},
    })
  );

  assert.doesNotMatch(html, /sk-[a-zA-Z0-9]{20,}/);
  assert.doesNotMatch(html, /xi-api-key/);
});

// Clean up Vite SSR server
await vite.close();
