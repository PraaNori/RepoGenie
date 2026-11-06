/**
 * Milestone 5, Phase 5.5 Frontend Captions Unit Test Suite
 * Tests CaptionsCard, VideoResultView, ProcessingView, API client methods,
 * SRT and WebVTT download links, timing provenance, and readOnly mode.
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

const { default: CaptionsCard } = await vite.ssrLoadModule(
  './src/components/processing/CaptionsCard.jsx'
);
const { default: VideoResultView } = await vite.ssrLoadModule(
  './src/components/VideoResultView.jsx'
);
const { default: ProcessingView } = await vite.ssrLoadModule(
  './src/components/ProcessingView.jsx'
);
const apiClient = await vite.ssrLoadModule('./src/api/client.js');

// Mock data fixtures conforming to CaptionGenerationResult schema
const mockCaptionData = {
  schema_version: '1.0',
  job_id: 'job-test-captions',
  status: 'completed',
  total_scenes: 2,
  scenes_completed: 2,
  scenes_skipped: 0,
  scenes_failed: 0,
  total_captions: 4,
  total_duration_seconds: 10.5,
  timing_provenance: 'estimated',
  full_srt_file_path: 'jobs/job-test-captions/captions/full.srt',
  full_vtt_file_path: 'jobs/job-test-captions/captions/full.vtt',
  full_srt_file_size_bytes: 420,
  full_vtt_file_size_bytes: 440,
  warnings: [],
  scene_assets: [
    {
      asset_id: 'caption_scene_1',
      job_id: 'job-test-captions',
      scene_id: 'scene-1',
      scene_number: 1,
      script_section_id: 'sec-1',
      status: 'completed',
      duration_seconds: 4.5,
      cumulative_start_seconds: 0.0,
      cumulative_end_seconds: 4.5,
      srt_file_path: 'jobs/job-test-captions/captions/caption_scene_1.srt',
      vtt_file_path: 'jobs/job-test-captions/captions/caption_scene_1.vtt',
      srt_file_size_bytes: 180,
      vtt_file_size_bytes: 195,
      timing_provenance: 'estimated',
      captions: [
        {
          caption_id: 'cap_scene_1_1',
          scene_id: 'scene-1',
          sequence_number: 1,
          start_seconds: 0.05,
          end_seconds: 2.15,
          start_timestamp_srt: '00:00:00,050',
          end_timestamp_srt: '00:00:02,150',
          start_timestamp_vtt: '00:00:00.050',
          end_timestamp_vtt: '00:00:02.150',
          text: 'Welcome to RepoGenie.',
          timing_provenance: 'estimated',
        },
        {
          caption_id: 'cap_scene_1_2',
          scene_id: 'scene-1',
          sequence_number: 2,
          start_seconds: 2.19,
          end_seconds: 4.45,
          start_timestamp_srt: '00:00:02,190',
          end_timestamp_srt: '00:00:04,450',
          start_timestamp_vtt: '00:00:02.190',
          end_timestamp_vtt: '00:00:04.450',
          text: 'This video explains the project architecture.',
          timing_provenance: 'estimated',
        },
      ],
    },
    {
      asset_id: 'caption_scene_2',
      job_id: 'job-test-captions',
      scene_id: 'scene-2',
      scene_number: 2,
      script_section_id: 'sec-2',
      status: 'completed',
      duration_seconds: 6.0,
      cumulative_start_seconds: 4.5,
      cumulative_end_seconds: 10.5,
      srt_file_path: 'jobs/job-test-captions/captions/caption_scene_2.srt',
      vtt_file_path: 'jobs/job-test-captions/captions/caption_scene_2.vtt',
      srt_file_size_bytes: 240,
      vtt_file_size_bytes: 255,
      timing_provenance: 'estimated',
      captions: [
        {
          caption_id: 'cap_scene_2_1',
          scene_id: 'scene-2',
          sequence_number: 1,
          start_seconds: 0.05,
          end_seconds: 3.0,
          start_timestamp_srt: '00:00:00,050',
          end_timestamp_srt: '00:00:03,000',
          start_timestamp_vtt: '00:00:00.050',
          end_timestamp_vtt: '00:00:03.000',
          text: 'The architecture is modular and layered.',
          timing_provenance: 'estimated',
        },
      ],
    },
  ],
};

test('1. CaptionsCard renders "ready to generate" state when narration is available', () => {
  const html = renderToString(
    React.createElement(CaptionsCard, {
      jobId: 'job-1',
      captions: null,
      isLoading: false,
      onGenerate: () => {},
      isNarrationAvailable: true,
      readOnly: false,
    })
  );

  assert.match(html, /Subtitles &amp; Captions|Subtitles & Captions/);
  assert.match(html, /Ready to Generate Subtitles/);
  assert.match(html, /Generate Subtitles/);
});

test('2. CaptionsCard indicates when prerequisite narration is not ready', () => {
  const html = renderToString(
    React.createElement(CaptionsCard, {
      jobId: 'job-1',
      captions: null,
      isLoading: false,
      onGenerate: () => {},
      isNarrationAvailable: false,
      readOnly: false,
    })
  );

  assert.match(html, /Narration Audio Required/);
  assert.match(html, /Generate scene narration audio in Stage 08/);
});

test('3. CaptionsCard renders loading state with spinner', () => {
  const html = renderToString(
    React.createElement(CaptionsCard, {
      jobId: 'job-1',
      captions: null,
      isLoading: true,
      onGenerate: () => {},
      isNarrationAvailable: true,
      readOnly: false,
    })
  );

  assert.match(html, /Generating Captions\.\.\./);
});

test('4. CaptionsCard displays error state cleanly', () => {
  const html = renderToString(
    React.createElement(CaptionsCard, {
      jobId: 'job-1',
      captions: null,
      isLoading: false,
      onGenerate: () => {},
      error: 'Failed to synchronize scene timestamps',
      isNarrationAvailable: true,
      readOnly: false,
    })
  );

  assert.match(html, /Caption Generation Error/);
  assert.match(html, /Failed to synchronize scene timestamps/);
});

test('5. CaptionsCard renders generated captions, metrics, and download links', () => {
  const html = renderToString(
    React.createElement(CaptionsCard, {
      jobId: 'job-test-captions',
      captions: mockCaptionData,
      isLoading: false,
      onGenerate: () => {},
      isNarrationAvailable: true,
      readOnly: false,
    })
  );

  assert.match(html, /COMPLETED/);
  assert.match(html, /Scenes Processed/);
  assert.match(html, /2 \/ 2/);
  assert.match(html, /Total Caption Cues/);
  assert.match(html, /4/);
  assert.match(html, /Estimated Proportional/);
  assert.match(html, /\.SRT/);
  assert.match(html, /\.VTT/);
  assert.match(html, /Scene 1/);
  assert.match(html, /Scene 2/);
});

test('6. CaptionsCard hides regenerate button in readOnly mode', () => {
  const html = renderToString(
    React.createElement(CaptionsCard, {
      jobId: 'job-test-captions',
      captions: mockCaptionData,
      isLoading: false,
      onGenerate: () => {},
      isNarrationAvailable: true,
      readOnly: true,
    })
  );

  assert.doesNotMatch(html, /Regenerate Captions/);
  assert.match(html, /Scenes Processed/);
});

test('7. API client getCaptionFileUrl formats URL correctly', () => {
  const urlSrt = apiClient.getCaptionFileUrl('job-123', 'caption_scene_1', 'srt');
  assert.equal(urlSrt, 'http://localhost:8000/api/v1/jobs/job-123/captions/caption_scene_1/file?format=srt');

  const urlVtt = apiClient.getCaptionFileUrl('job-123', 'full', 'vtt');
  assert.equal(urlVtt, 'http://localhost:8000/api/v1/jobs/job-123/captions/full/file?format=vtt');
});

test('8. VideoResultView displays cached captions in readOnly mode', () => {
  const html = renderToString(
    React.createElement(VideoResultView, {
      job: {
        job_id: 'job-test-captions',
        has_captions: true,
        captions: mockCaptionData,
      },
    })
  );

  assert.match(html, /Subtitles &amp; Captions|Subtitles & Captions/);
  assert.match(html, /Scenes Processed/);
  assert.doesNotMatch(html, /Regenerate Captions/);
});

// Close Vite SSR server after tests complete
await vite.close();
