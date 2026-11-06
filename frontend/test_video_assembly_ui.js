/**
 * Milestone 6, Phase 6.1 Frontend Video Assembly Foundation Test Suite
 * Tests VideoAssemblyCard, ProcessingView, VideoResultView, and API client methods.
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

const { default: VideoAssemblyCard } = await vite.ssrLoadModule(
  './src/components/processing/VideoAssemblyCard.jsx'
);
const { default: VideoAssemblyCardAlias } = await vite.ssrLoadModule(
  './src/components/VideoAssemblyCard.jsx'
);
const { default: VideoResultView } = await vite.ssrLoadModule(
  './src/components/VideoResultView.jsx'
);
const { default: ProcessingView } = await vite.ssrLoadModule(
  './src/components/ProcessingView.jsx'
);
const apiClient = await vite.ssrLoadModule('./src/api/client.js');

const mockSystemStatusAvailable = {
  is_ready: true,
  ffmpeg: {
    name: 'ffmpeg',
    is_available: true,
    executable_path: '/usr/local/bin/ffmpeg',
    version: '6.1.1',
    codecs_supported: ['libx264', 'aac'],
  },
  ffprobe: {
    name: 'ffprobe',
    is_available: true,
    executable_path: '/usr/local/bin/ffprobe',
    version: '6.1.1',
  },
  default_configuration: {
    resolution_width: 1920,
    resolution_height: 1080,
    fps: 30,
    video_codec: 'libx264',
    pixel_format: 'yuv420p',
    audio_codec: 'aac',
    audio_sample_rate: 44100,
    container_format: 'mp4',
  },
};

const mockSystemStatusMissing = {
  is_ready: false,
  ffmpeg: {
    name: 'ffmpeg',
    is_available: false,
    executable_path: null,
    version: null,
    error: 'FFmpeg binary not found in system PATH',
  },
  ffprobe: {
    name: 'ffprobe',
    is_available: false,
    executable_path: null,
    version: null,
    error: 'FFprobe binary not found in system PATH',
  },
  default_configuration: {
    resolution_width: 1920,
    resolution_height: 1080,
    fps: 30,
    video_codec: 'libx264',
    pixel_format: 'yuv420p',
    audio_codec: 'aac',
    audio_sample_rate: 44100,
    container_format: 'mp4',
  },
};

test('Video Assembly API Client exports expected methods', () => {
  assert.equal(typeof apiClient.getVideoSystemStatus, 'function');
  assert.equal(typeof apiClient.getJobRenderConfig, 'function');
  assert.equal(typeof apiClient.updateJobRenderConfig, 'function');
  assert.equal(typeof apiClient.getJobRender, 'function');
  assert.equal(typeof apiClient.getSceneRenders, 'function');
  assert.equal(typeof apiClient.renderScenes, 'function');
  assert.equal(typeof apiClient.getSingleSceneRender, 'function');
  assert.equal(typeof apiClient.getSceneRenderFileUrl, 'function');
});

test('VideoAssemblyCard renders FFMPEG READY status badge and versions', () => {
  const html = renderToString(
    React.createElement(VideoAssemblyCard, {
      jobId: 'job-video-1',
      systemStatus: mockSystemStatusAvailable,
    })
  );

  assert.ok(html.includes('Video Assembly'));
  assert.ok(html.includes('FFMPEG READY'));
  assert.ok(html.includes('v6.1.1'));
  assert.ok(html.includes('1920 × 1080'));
  assert.ok(html.includes('30 FPS'));
  assert.ok(html.includes('libx264'));
  assert.ok(html.includes('aac'));
});

test('VideoAssemblyCard renders BINARIES MISSING warning state cleanly', () => {
  const html = renderToString(
    React.createElement(VideoAssemblyCard, {
      jobId: 'job-video-2',
      systemStatus: mockSystemStatusMissing,
    })
  );

  assert.ok(html.includes('BINARIES MISSING'));
  assert.ok(html.includes('Not Installed'));
  assert.ok(html.includes('FFmpeg binary not found in system PATH'));
});

test('VideoAssemblyCard supports readOnly mode without refresh button', () => {
  const normalHtml = renderToString(
    React.createElement(VideoAssemblyCard, {
      jobId: 'job-video-3',
      systemStatus: mockSystemStatusAvailable,
      readOnly: false,
    })
  );
  assert.ok(normalHtml.includes('title="Refresh status"'));

  const readOnlyHtml = renderToString(
    React.createElement(VideoAssemblyCard, {
      jobId: 'job-video-3',
      systemStatus: mockSystemStatusAvailable,
      readOnly: true,
    })
  );
  assert.ok(!readOnlyHtml.includes('title="Refresh status"'));
});

test('VideoAssemblyCard re-export alias functions identically', () => {
  const html = renderToString(
    React.createElement(VideoAssemblyCardAlias, {
      jobId: 'job-alias-1',
      systemStatus: mockSystemStatusAvailable,
    })
  );
  assert.ok(html.includes('Video Assembly'));
  assert.ok(html.includes('FFMPEG READY'));
});

test('ProcessingView renders VideoAssemblyCard when assembly input or storyboard exists', () => {
  const dummyJob = {
    job_id: 'job-proc-1',
    repo_name: 'test/repo',
    has_assembly_input: true,
    has_educational_storyboard: true,
    stages: [
      { id: 9, name: 'Video Assembly', status: 'pending', detail: 'Ready for video assembly' },
    ],
  };

  const html = renderToString(
    React.createElement(ProcessingView, {
      job: dummyJob,
      assemblyInput: { scenes: [{ scene_id: 's1' }] },
      educationalStoryboard: { scenes: [] },
      onBack: () => {},
    })
  );

  assert.ok(html.includes('Video Assembly'));
});

test('VideoResultView renders VideoAssemblyCard in readOnly mode', () => {
  const dummyJob = {
    job_id: 'job-res-1',
    repo_name: 'test/repo',
    has_assembly_input: true,
    assembly_input: {
      total_scenes: 1,
      total_duration_seconds: 5.0,
      scenes: [{ scene_id: 's1', scene_number: 1, title: 'Scene 1', start_seconds: 0.0, end_seconds: 5.0, duration_seconds: 5.0, is_ready: true }],
      readiness_report: { status: 'ready', blocking_issues: [], warnings: [] },
    },
  };

  const html = renderToString(
    React.createElement(VideoResultView, {
      job: dummyJob,
      onReset: () => {},
    })
  );

  assert.ok(html.includes('Video Assembly'));
});

// ==============================================================================
// Phase 6.2: Scene Rendering Frontend Tests
// ==============================================================================

test('VideoAssemblyCard renders Phase 6.2 scene rendering section and Render Scenes action', () => {
  const html = renderToString(
    React.createElement(VideoAssemblyCard, {
      jobId: 'job-scene-1',
      systemStatus: mockSystemStatusAvailable,
      readOnly: false,
    })
  );

  assert.ok(html.includes('Scene Video Segments (Phase 6.2)'));
  assert.ok(html.includes('Render Scenes'));
  assert.ok(html.includes('Force Refresh'));
  assert.ok(html.includes('NOT RENDERED'));
});

test('VideoAssemblyCard renders completed scene list, metrics, and download links', () => {
  const mockSceneResult = {
    job_id: 'job-scene-2',
    total_scenes: 2,
    completed_scenes: 2,
    failed_scenes: 0,
    is_complete: true,
    render_duration_seconds: 4.5,
    scenes: [
      {
        scene_id: 'sc-1',
        scene_number: 1,
        title: 'Project Architecture',
        status: 'completed',
        is_silent: false,
        actual_duration_seconds: 6.2,
        expected_duration_seconds: 6.0,
        output_relative_path: 'jobs/job-scene-2/video/scenes/scene_01_sc-1.mp4',
      },
      {
        scene_id: 'sc-2',
        scene_number: 2,
        title: 'Summary Card',
        status: 'completed',
        is_silent: true,
        actual_duration_seconds: 4.0,
        expected_duration_seconds: 4.0,
        output_relative_path: 'jobs/job-scene-2/video/scenes/scene_02_sc-2.mp4',
      },
    ],
  };

  const html = renderToString(
    React.createElement(VideoAssemblyCard, {
      jobId: 'job-scene-2',
      systemStatus: mockSystemStatusAvailable,
      sceneRenders: mockSceneResult,
      readOnly: false,
    })
  );

  assert.ok(html.includes('ALL SCENES RENDERED'));
  assert.ok(html.includes('Project Architecture'));
  assert.ok(html.includes('Summary Card'));
  assert.ok(html.includes('6.2s'));
  assert.ok(html.includes('4.0s'));
  assert.ok(html.includes('Narrated'));
  assert.ok(html.includes('Silent'));
  assert.ok(html.includes('/api/v1/jobs/job-scene-2/render-scenes/sc-1/file'));
});

test('VideoAssemblyCard hides Render Scenes button in readOnly mode', () => {
  const html = renderToString(
    React.createElement(VideoAssemblyCard, {
      jobId: 'job-scene-ro',
      systemStatus: mockSystemStatusAvailable,
      readOnly: true,
    })
  );

  assert.ok(!html.includes('Render Scenes'));
  assert.ok(!html.includes('Force Refresh'));
});

// Close Vite SSR server after tests complete
await vite.close();
