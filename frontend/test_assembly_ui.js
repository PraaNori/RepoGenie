/**
 * Milestone 5, Phase 5.6 Frontend Assembly Input & Readiness Test Suite
 * Tests AssemblyReadinessCard, ProcessingView, VideoResultView, and API client methods.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Start Vite SSR server to dynamically load and transform JSX components
const vite = await createServer({
  root: __dirname,
  server: { middlewareMode: true, hmr: false, ws: false },
  appType: 'custom',
});

const { default: AssemblyReadinessCard } = await vite.ssrLoadModule(
  './src/components/processing/AssemblyReadinessCard.jsx'
);
const { default: AssemblyReadinessCardAlias } = await vite.ssrLoadModule(
  './src/components/AssemblyReadinessCard.jsx'
);
const { default: VideoResultView } = await vite.ssrLoadModule(
  './src/components/VideoResultView.jsx'
);
const { default: ProcessingView } = await vite.ssrLoadModule(
  './src/components/ProcessingView.jsx'
);
const apiClient = await vite.ssrLoadModule('./src/api/client.js');

const mockReadyAssemblyInput = {
  job_id: 'job-assembly-test-1',
  repo_name: 'test-org/test-repo',
  total_scenes: 2,
  total_duration_seconds: 12.5,
  scenes: [
    {
      scene_id: 'scene-1',
      scene_number: 1,
      script_section_id: 'sec-1',
      section_purpose: 'hook_introduction',
      title: 'Introduction Scene',
      start_seconds: 0.0,
      end_seconds: 6.0,
      duration_seconds: 6.0,
      is_silent: false,
      narration_text: 'Welcome to this deep dive into test-repo.',
      is_ready: true,
      issues: [],
      visual_asset: {
        asset_id: 'vis_scene_1',
        scene_id: 'scene-1',
        asset_type: 'visual',
        relative_path: 'jobs/job-assembly-test-1/visuals/vis_scene_1.svg',
        file_format: 'svg',
        file_size_bytes: 2048,
        is_valid: true,
      },
      narration_asset: {
        asset_id: 'audio_scene_1',
        scene_id: 'scene-1',
        asset_type: 'narration',
        relative_path: 'jobs/job-assembly-test-1/audio/audio_scene_1.mp3',
        file_format: 'mp3',
        file_size_bytes: 18400,
        duration_seconds: 6.0,
        is_valid: true,
      },
      caption_srt_asset: {
        asset_id: 'caption_scene_1',
        scene_id: 'scene-1',
        asset_type: 'caption_srt',
        relative_path: 'jobs/job-assembly-test-1/captions/caption_scene_1.srt',
        file_format: 'srt',
        file_size_bytes: 220,
        is_valid: true,
      },
      caption_vtt_asset: {
        asset_id: 'caption_scene_1',
        scene_id: 'scene-1',
        asset_type: 'caption_vtt',
        relative_path: 'jobs/job-assembly-test-1/captions/caption_scene_1.vtt',
        file_format: 'vtt',
        file_size_bytes: 240,
        is_valid: true,
      },
    },
    {
      scene_id: 'scene-2',
      scene_number: 2,
      script_section_id: 'sec-2',
      section_purpose: 'architecture_overview',
      title: 'Architecture Overview Scene',
      start_seconds: 6.0,
      end_seconds: 12.5,
      duration_seconds: 6.5,
      is_silent: false,
      narration_text: 'The architecture consists of three core components.',
      is_ready: true,
      issues: [],
      visual_asset: {
        asset_id: 'vis_scene_2',
        scene_id: 'scene-2',
        asset_type: 'visual',
        relative_path: 'jobs/job-assembly-test-1/visuals/vis_scene_2.svg',
        file_format: 'svg',
        file_size_bytes: 4096,
        is_valid: true,
      },
      narration_asset: {
        asset_id: 'audio_scene_2',
        scene_id: 'scene-2',
        asset_type: 'narration',
        relative_path: 'jobs/job-assembly-test-1/audio/audio_scene_2.mp3',
        file_format: 'mp3',
        file_size_bytes: 21000,
        duration_seconds: 6.5,
        is_valid: true,
      },
      caption_srt_asset: {
        asset_id: 'caption_scene_2',
        scene_id: 'scene-2',
        asset_type: 'caption_srt',
        relative_path: 'jobs/job-assembly-test-1/captions/caption_scene_2.srt',
        file_format: 'srt',
        file_size_bytes: 260,
        is_valid: true,
      },
      caption_vtt_asset: {
        asset_id: 'caption_scene_2',
        scene_id: 'scene-2',
        asset_type: 'caption_vtt',
        relative_path: 'jobs/job-assembly-test-1/captions/caption_scene_2.vtt',
        file_format: 'vtt',
        file_size_bytes: 280,
        is_valid: true,
      },
    },
  ],
  full_video_srt: {
    asset_id: 'full_video',
    asset_type: 'full_video_srt',
    relative_path: 'jobs/job-assembly-test-1/captions/full_video.srt',
    file_format: 'srt',
    file_size_bytes: 600,
    duration_seconds: 12.5,
    is_valid: true,
  },
  full_video_vtt: {
    asset_id: 'full_video',
    asset_type: 'full_video_vtt',
    relative_path: 'jobs/job-assembly-test-1/captions/full_video.vtt',
    file_format: 'vtt',
    file_size_bytes: 640,
    duration_seconds: 12.5,
    is_valid: true,
  },
  readiness_report: {
    job_id: 'job-assembly-test-1',
    status: 'ready',
    total_scenes: 2,
    ready_scenes: 2,
    total_duration_seconds: 12.5,
    has_visuals: true,
    has_narration: true,
    has_captions: true,
    has_full_video_captions: true,
    blocking_issues: [],
    warnings: [],
  },
};

const mockWarningAssemblyInput = {
  ...mockReadyAssemblyInput,
  readiness_report: {
    ...mockReadyAssemblyInput.readiness_report,
    status: 'ready_with_warnings',
    warnings: [
      {
        code: 'TIMELINE_GAP',
        severity: 'warning',
        message: 'Scene 2 has a timeline gap of 0.08s from preceding scene.',
        scene_id: 'scene-2',
        scene_number: 2,
      },
    ],
  },
};

const mockNotReadyAssemblyInput = {
  ...mockReadyAssemblyInput,
  readiness_report: {
    ...mockReadyAssemblyInput.readiness_report,
    status: 'not_ready',
    ready_scenes: 1,
    has_narration: false,
    blocking_issues: [
      {
        code: 'MISSING_NARRATION_ASSET',
        severity: 'blocking',
        message: 'Non-silent scene 2 is missing narration audio.',
        scene_id: 'scene-2',
        scene_number: 2,
      },
    ],
  },
};

test('Assembly API Client exports expected methods', () => {
  assert.equal(typeof apiClient.getAssemblyInput, 'function');
  assert.equal(typeof apiClient.generateAssemblyInput, 'function');
  assert.equal(typeof apiClient.getAssemblyReadiness, 'function');
});

test('AssemblyReadinessCard renders unverified empty state when assemblyInput is null', () => {
  const html = renderToString(
    React.createElement(AssemblyReadinessCard, {
      jobId: 'job-assembly-empty',
      assemblyInput: null,
      isStoryboardAvailable: true,
    })
  );

  assert.ok(html.includes('Video Assembly Input &amp; Readiness'));
  assert.ok(html.includes('UNVERIFIED'));
  assert.ok(html.includes('No Assembly Package Compiled'));
  assert.ok(html.includes('Validate Assembly Readiness'));
});

test('AssemblyReadinessCard renders READY status badge and metrics', () => {
  const html = renderToString(
    React.createElement(AssemblyReadinessCard, {
      jobId: 'job-assembly-test-1',
      assemblyInput: mockReadyAssemblyInput,
      isStoryboardAvailable: true,
    })
  );

  assert.ok(html.includes('READY FOR ASSEMBLY'));
  assert.ok(html.includes('2 / 2'));
  assert.ok(html.includes('12.5s'));
  assert.ok(html.includes('All Verified'));
  assert.ok(html.includes('Synced'));
  assert.ok(html.includes('Introduction Scene'));
  assert.ok(html.includes('Architecture Overview Scene'));
});

test('AssemblyReadinessCard renders READY WITH WARNINGS badge and warning messages', () => {
  const html = renderToString(
    React.createElement(AssemblyReadinessCard, {
      jobId: 'job-assembly-test-1',
      assemblyInput: mockWarningAssemblyInput,
      isStoryboardAvailable: true,
    })
  );

  assert.ok(html.includes('READY WITH WARNINGS'));
  assert.ok(html.includes('Advisory Warnings (1)'));
  assert.ok(html.includes('[TIMELINE_GAP]'));
  assert.ok(html.includes('timeline gap of 0.08s'));
});

test('AssemblyReadinessCard renders NOT READY status badge and blocking issues', () => {
  const html = renderToString(
    React.createElement(AssemblyReadinessCard, {
      jobId: 'job-assembly-test-1',
      assemblyInput: mockNotReadyAssemblyInput,
      isStoryboardAvailable: true,
    })
  );

  assert.ok(html.includes('NOT READY'));
  assert.ok(html.includes('Blocking Issues (1)'));
  assert.ok(html.includes('[MISSING_NARRATION_ASSET]'));
  assert.ok(html.includes('missing narration audio'));
});

test('AssemblyReadinessCard supports readOnly mode without action buttons', () => {
  const html = renderToString(
    React.createElement(AssemblyReadinessCard, {
      jobId: 'job-assembly-test-1',
      assemblyInput: mockReadyAssemblyInput,
      readOnly: true,
    })
  );

  assert.ok(html.includes('READY FOR ASSEMBLY'));
  assert.ok(!html.includes('Revalidate Assembly Package'));
  assert.ok(!html.includes('Validate Assembly Readiness'));
});

test('AssemblyReadinessCard re-export alias functions identically', () => {
  const html = renderToString(
    React.createElement(AssemblyReadinessCardAlias, {
      jobId: 'job-assembly-test-1',
      assemblyInput: mockReadyAssemblyInput,
      readOnly: true,
    })
  );

  assert.ok(html.includes('READY FOR ASSEMBLY'));
  assert.ok(html.includes('Scene Assembly Timeline'));
});

test('ProcessingView renders AssemblyReadinessCard when assembly input or storyboard is present', () => {
  const mockJob = {
    job_id: 'job-proc-test',
    repo_name: 'test-org/test-repo',
    status: 'in_progress',
    current_stage: 'visual_generation',
    progress_percentage: 75,
    has_educational_storyboard: true,
    has_assembly_input: true,
    assembly_input: mockReadyAssemblyInput,
    stages: [
      { id: 1, name: 'repo_fetching', status: 'completed' },
      { id: 2, name: 'repo_analysis', status: 'completed' },
      { id: 3, name: 'code_understanding', status: 'completed' },
      { id: 4, name: 'ai_summary', status: 'completed' },
      { id: 5, name: 'script_generation', status: 'completed' },
      { id: 6, name: 'storyboard_generation', status: 'completed' },
      { id: 7, name: 'visual_generation', status: 'completed' },
      { id: 8, name: 'voice_generation', status: 'completed' },
      { id: 9, name: 'video_assembly', status: 'pending' },
    ],
  };

  const html = renderToString(
    React.createElement(ProcessingView, {
      job: mockJob,
    })
  );

  assert.ok(html.includes('Video Assembly Input &amp; Readiness'));
  assert.ok(html.includes('READY FOR ASSEMBLY'));
});

// Close Vite SSR server after tests complete
await vite.close();

test('VideoResultView renders AssemblyReadinessCard in readOnly mode', () => {
  const mockJob = {
    job_id: 'job-result-test',
    repo_name: 'test-org/test-repo',
    status: 'completed',
    has_assembly_input: true,
    assembly_input: mockReadyAssemblyInput,
    result: {
      repo_name: 'test-repo',
      repo_url: 'https://github.com/test-org/test-repo',
      description: 'Educational walkthrough of test-repo',
      tech_stack: ['Python', 'FastAPI'],
      summary: 'Architecture summary',
      video_url: 'https://example.com/video.mp4',
      duration_seconds: 12.5,
    },
  };

  const html = renderToString(
    React.createElement(VideoResultView, {
      job: mockJob,
    })
  );

  assert.ok(html.includes('Video Assembly Input &amp; Readiness'));
  assert.ok(html.includes('READY FOR ASSEMBLY'));
});

// Close Vite SSR server after tests complete
await vite.close();
