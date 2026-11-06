/**
 * Milestone 7: Frontend/Backend Integration & Final UI Verification Tests
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

const { default: VisualGenerationCard } = await vite.ssrLoadModule(
  './src/components/processing/VisualGenerationCard.jsx'
);
const { default: ProcessingView } = await vite.ssrLoadModule(
  './src/components/ProcessingView.jsx'
);
const { default: VideoResultView } = await vite.ssrLoadModule(
  './src/components/VideoResultView.jsx'
);
const apiClient = await vite.ssrLoadModule('./src/api/client.js');

test('1. Milestone 7 API Client exports expected integration methods', () => {
  assert.equal(typeof apiClient.runFullPipeline, 'function');
  assert.equal(typeof apiClient.retryJobStage, 'function');
  assert.equal(typeof apiClient.getVisualAssets, 'function');
  assert.equal(typeof apiClient.generateVisualAssets, 'function');
  assert.equal(typeof apiClient.getVisualAssetFileUrl, 'function');

  const fileUrl = apiClient.getVisualAssetFileUrl('test-job-123', 'asset-456');
  assert.match(fileUrl, /\/api\/v1\/jobs\/test-job-123\/visual-assets\/asset-456\/file/);
});

test('2. VisualGenerationCard renders uninitialized state when visualGeneration is null', () => {
  const html = renderToString(
    React.createElement(VisualGenerationCard, {
      jobId: 'job-123',
      visualGeneration: null,
      hasStoryboard: true,
      isLoading: false,
    })
  );

  assert.match(html, /Stage 07: Visual Asset Generation/);
  assert.match(html, /Pending/);
  assert.match(html, /Generate Visuals/);
});

test('3. VisualGenerationCard warns when storyboard prerequisite is missing', () => {
  const html = renderToString(
    React.createElement(VisualGenerationCard, {
      jobId: 'job-123',
      visualGeneration: null,
      hasStoryboard: false,
      isLoading: false,
    })
  );

  assert.match(html, /Educational Storyboard \(Stage 06\) must be generated first/);
});

test('4. VisualGenerationCard renders completed state with scene metrics and thumbnails', () => {
  const sampleVisualGeneration = {
    job_id: 'job-123',
    status: 'completed',
    total_scenes: 2,
    rendered_scenes_count: 2,
    is_fully_rendered: true,
    assets: [
      {
        scene_id: 'scene-1',
        scene_number: 1,
        visual_type: 'architecture_diagram',
        description: 'System architecture diagram preview',
        visual_assets: [
          {
            asset_id: 'asset-1',
            status: 'rendered',
            media_format: 'svg',
            storage_path: 'scenes/scene_1.svg',
          },
        ],
      },
      {
        scene_id: 'scene-2',
        scene_number: 2,
        visual_type: 'code_highlight',
        description: 'AST code snippet highlights',
        visual_assets: [
          {
            asset_id: 'asset-2',
            status: 'rendered',
            media_format: 'svg',
            storage_path: 'scenes/scene_2.svg',
          },
        ],
      },
    ],
  };

  const html = renderToString(
    React.createElement(VisualGenerationCard, {
      jobId: 'job-123',
      visualGeneration: sampleVisualGeneration,
      readOnly: false,
    })
  );

  assert.match(html, /Completed/);
  assert.match(html, /Scene #1/);
  assert.match(html, /Scene #2/);
  assert.match(html, /architecture_diagram/);
  assert.match(html, /code_highlight/);
  assert.match(html, /Regenerate/);
});

test('5. VisualGenerationCard hides regenerate button in readOnly mode', () => {
  const sampleVisualGeneration = {
    job_id: 'job-123',
    status: 'completed',
    total_scenes: 1,
    rendered_scenes_count: 1,
    is_fully_rendered: true,
    assets: [],
  };

  const html = renderToString(
    React.createElement(VisualGenerationCard, {
      jobId: 'job-123',
      visualGeneration: sampleVisualGeneration,
      readOnly: true,
    })
  );

  assert.doesNotMatch(html, /Regenerate/);
});

test('6. ProcessingView renders Auto-Run Pipeline button and VisualGenerationCard', () => {
  const sampleJob = {
    job_id: 'job-m7',
    repo_name: 'test/repo',
    repo_url: 'https://github.com/test/repo',
    status: 'in_progress',
    current_stage: 'Visual Generation',
    progress_percentage: 65,
    has_educational_storyboard: true,
    has_visual_generation: true,
    stages: [
      { id: 1, name: 'Repository Fetching', status: 'completed' },
      { id: 2, name: 'Repository Analysis', status: 'completed' },
      { id: 3, name: 'Code Understanding', status: 'completed' },
      { id: 4, name: 'AI Summary Generation', status: 'completed' },
      { id: 5, name: 'Script Generation', status: 'completed' },
      { id: 6, name: 'Storyboard Generation', status: 'completed' },
      { id: 7, name: 'Visual Generation', status: 'in_progress' },
      { id: 8, name: 'Voice Generation', status: 'pending' },
      { id: 9, name: 'Video Assembly', status: 'pending' },
    ],
  };

  const html = renderToString(
    React.createElement(ProcessingView, {
      job: sampleJob,
    })
  );

  assert.match(html, /Auto-Run Pipeline/);
  assert.match(html, /Simulate Next Stage/);
  assert.match(html, /Stage 07: Visual Asset Generation/);
});

test('7. ProcessingView displays actionable Retry Stage button when a stage fails', () => {
  const failedJob = {
    job_id: 'job-m7-failed',
    repo_name: 'test/repo',
    repo_url: 'https://github.com/test/repo',
    status: 'failed',
    error: 'AI quota temporarily exhausted for Stage 5',
    stages: [
      { id: 1, name: 'Repository Fetching', status: 'completed' },
      { id: 2, name: 'Repository Analysis', status: 'completed' },
      { id: 3, name: 'Code Understanding', status: 'completed' },
      { id: 4, name: 'AI Summary Generation', status: 'completed' },
      { id: 5, name: 'Script Generation', status: 'failed', detail: 'Quota exhausted' },
      { id: 6, name: 'Storyboard Generation', status: 'pending' },
      { id: 7, name: 'Visual Generation', status: 'pending' },
      { id: 8, name: 'Voice Generation', status: 'pending' },
      { id: 9, name: 'Video Assembly', status: 'pending' },
    ],
  };

  const html = renderToString(
    React.createElement(ProcessingView, {
      job: failedJob,
    })
  );

  assert.match(html, /Pipeline Execution Error/);
  assert.match(html, /Retry Stage 5/);
});

test('8. VideoResultView displays Visual Assets section in readOnly mode', () => {
  const completedJob = {
    job_id: 'job-m7-done',
    repo_name: 'test/repo',
    repo_url: 'https://github.com/test/repo',
    status: 'completed',
    progress_percentage: 100,
    has_visual_generation: true,
    visual_generation: {
      job_id: 'job-m7-done',
      status: 'completed',
      total_scenes: 1,
      rendered_scenes_count: 1,
      is_fully_rendered: true,
      assets: [
        {
          scene_id: 's1',
          scene_number: 1,
          visual_type: 'architecture_diagram',
          description: 'Verified Architecture Flow',
          visual_assets: [
            { asset_id: 'a1', status: 'rendered', media_format: 'svg', storage_path: 'a1.svg' },
          ],
        },
      ],
    },
    result: {
      repo_name: 'test/repo',
      repo_url: 'https://github.com/test/repo',
      description: 'Educational video for test/repo',
      tech_stack: ['Python'],
      summary: 'Architectural overview',
      duration_seconds: 45,
    },
  };

  const html = renderToString(
    React.createElement(VideoResultView, {
      job: completedJob,
    })
  );

  assert.match(html, /Stage 07: Visual Asset Generation/);
  assert.match(html, /Verified Architecture Flow/);
  // Verify dynamic duration formatting (00:45)
  assert.match(html, /Duration: 00:45/);
  assert.doesNotMatch(html, /Duration: 03:00/);
});

await vite.close();

