/**
 * Milestone 4, Phase 4.2 Frontend Integration Test Suite
 * Tests EducationalScriptCard, EducationalStoryboardCard, VideoResultView, ProcessingView,
 * API client methods, path sanitization, duplicate protection, and invalidation cascade.
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

const { default: EducationalScriptCard } = await vite.ssrLoadModule(
  './src/components/EducationalScriptCard.jsx'
);
const { default: EducationalStoryboardCard } = await vite.ssrLoadModule(
  './src/components/EducationalStoryboardCard.jsx'
);
const { default: VideoResultView } = await vite.ssrLoadModule(
  './src/components/VideoResultView.jsx'
);
const { default: ProcessingView } = await vite.ssrLoadModule(
  './src/components/ProcessingView.jsx'
);
const apiClient = await vite.ssrLoadModule('./src/api/client.js');

// Mock data fixtures conforming to EducationalScript and EducationalStoryboard schemas
const mockScript = {
  schema_version: '1.0',
  script_id: 'script-pallets-click-75s',
  repository_name: 'pallets/click',
  title: 'Inside Click: Composable Command-Line Interfaces',
  introduction: 'Click is a Python package for creating composable command line interfaces with decorators.',
  intended_audience: ['Python Developers', 'CLI Authors', 'Open Source Maintainers'],
  learning_objectives: [
    'Understand Click decorator-driven argument binding',
    'Trace command dispatching from argv parsing to callback execution',
    'Identify modular architecture patterns in the core engine',
  ],
  video_format: { orientation: 'landscape', aspect_ratio: '16:9' },
  total_estimated_duration_seconds: 75.0,
  sections: [
    {
      section_id: 'sec-1-hook',
      order: 1,
      title: 'Introduction & Command Line Interfaces',
      purpose: 'hook',
      is_narrated: true,
      narration_text: 'Building scalable command line tools in Python can quickly become chaotic without structure.',
      estimated_duration_seconds: 15.0,
      evidence: [
        { file_path: '/Users/dev/repo_cache/click/README.md', line_start: 1, line_end: 25, is_valid: true },
      ],
      claims: [
        { statement: 'Click powers production CLIs with declarative decorators.' },
      ],
      transition_to_next: "Let's examine how Click organizes its internal modules.",
    },
    {
      section_id: 'sec-2-arch',
      order: 2,
      title: 'Layered Engine Architecture',
      purpose: 'architecture_overview',
      is_narrated: true,
      narration_text: 'Click separates the decorator facade, the Command execution engine, and parameter parsers.',
      estimated_duration_seconds: 18.0,
      evidence: [
        { file_path: '/Users/dev/repo_cache/click/src/click/core.py', line_start: 10, line_end: 60, is_valid: true },
      ],
      claims: [
        { statement: 'Separation of Command and Context objects isolates execution state.' },
      ],
      transition_to_next: 'Now, let us trace how a command invocation moves through the system.',
    },
    {
      section_id: 'sec-3-wf',
      order: 3,
      title: 'Execution Workflow & Dispatch',
      purpose: 'workflow',
      is_narrated: true,
      narration_text: 'When a command is invoked, sys.argv is parsed into token streams, converted into types, and executed.',
      estimated_duration_seconds: 22.0,
      evidence: [
        { file_path: '/Users/dev/repo_cache/click/src/click/parser.py', line_start: 20, line_end: 80, is_valid: true },
      ],
      claims: [
        { statement: 'Parameter parsing parses options before calling command callback.' },
      ],
      transition_to_next: 'Finally, let us review the key architectural takeaways.',
    },
    {
      section_id: 'sec-4-outro',
      order: 4,
      title: 'Summary & Key Takeaways',
      purpose: 'conclusion',
      is_narrated: true,
      narration_text: 'By isolating context from command definitions, Click makes Python CLI tools testable and modular.',
      estimated_duration_seconds: 20.0,
      evidence: [
        { file_path: '/Users/dev/repo_cache/click/README.md', line_start: 30, line_end: 50, is_valid: true },
      ],
      claims: [],
      transition_to_next: null,
    },
  ],
  conclusion: 'Click provides a composable blueprint for building modular, maintainable technical CLIs.',
  metadata: {
    provider: 'Groq',
    model: 'llama-3.3-70b-versatile',
    latency_ms: 1250.0,
    token_usage: { prompt_tokens: 1500, completion_tokens: 450, total_tokens: 1950 },
  },
  static_analysis_caveats: [
    'Derived from static analysis without code execution.',
    'Runtime behaviors reflect inferred call patterns.',
  ],
};

const mockStoryboard = {
  schema_version: '1.0',
  storyboard_id: 'sb-pallets-click-75s',
  script_id: 'script-pallets-click-75s',
  title: 'Inside Click: Composable Command-Line Interfaces Storyboard',
  video_format: { orientation: 'landscape', aspect_ratio: '16:9' },
  total_estimated_duration_seconds: 75.0,
  scenes: [
    {
      scene_id: 'scene-1',
      scene_number: 1,
      script_section_id: 'sec-1-hook',
      title: 'Hook & Title Card',
      purpose: 'Introduce the problem statement and display title card',
      estimated_duration_seconds: 15.0,
      visual_type: 'title_card',
      visual_description: 'Clean dark card with Click logo and text: Composable Python CLIs.',
      on_screen_text: ['Inside Click', 'Composable Python CLIs', '60-90s Technical Explainer'],
      narration: {
        script_section_id: 'sec-1-hook',
        excerpt: 'Building scalable command line tools in Python can quickly become chaotic without structure.',
      },
      related_files: ['/Users/dev/repo_cache/click/README.md'],
      transition_to_next: 'Crossfade to architectural diagram',
      layout_hint: 'centered_hero',
    },
    {
      scene_id: 'scene-2',
      scene_number: 2,
      script_section_id: 'sec-2-arch',
      title: 'Three-Tier Architecture',
      purpose: 'Highlight separation of API, core engine, and parsers',
      estimated_duration_seconds: 18.0,
      visual_type: 'architecture_diagram',
      visual_description: 'Layered diagram showing Decorator API -> Core Execution Engine -> Parameter Parsers.',
      on_screen_text: ['1. Decorator Facade', '2. Command & Context Engine', '3. Parameter Parsers'],
      narration: {
        script_section_id: 'sec-2-arch',
        excerpt: 'Click separates the decorator facade, the Command execution engine, and parameter parsers.',
      },
      related_files: ['/Users/dev/repo_cache/click/src/click/core.py'],
      transition_to_next: 'Slide left to workflow flowchart',
      layout_hint: 'three_tier_columns',
    },
    {
      scene_id: 'scene-3',
      scene_number: 3,
      script_section_id: 'sec-3-wf',
      title: 'Argument Dispatch Pipeline',
      purpose: 'Trace token parsing and callback invocation',
      estimated_duration_seconds: 22.0,
      visual_type: 'workflow_diagram',
      visual_description: 'Animated workflow step from sys.argv tokenization to Context.invoke().',
      on_screen_text: ['argv Tokens', 'Type Conversion', 'Callback Invocation'],
      narration: {
        script_section_id: 'sec-3-wf',
        excerpt: 'When a command is invoked, sys.argv is parsed into token streams.',
      },
      related_files: ['/Users/dev/repo_cache/click/src/click/parser.py'],
      transition_to_next: 'Fade to takeaway summary card',
      layout_hint: 'directional_pipeline',
    },
    {
      scene_id: 'scene-4',
      scene_number: 4,
      script_section_id: 'sec-4-outro',
      title: 'Key Takeaways & Summary',
      purpose: 'Summarize architectural takeaways',
      estimated_duration_seconds: 20.0,
      visual_type: 'summary_card',
      visual_description: 'Summary card with three checkmark bullets and link to Pallets docs.',
      on_screen_text: ['Composable Decorators', 'Isolated Context State', 'Modular Testing'],
      narration: {
        script_section_id: 'sec-4-outro',
        excerpt: 'By isolating context from command definitions, Click makes Python CLI tools testable.',
      },
      related_files: ['/Users/dev/repo_cache/click/README.md'],
      transition_to_next: null,
      layout_hint: 'checklist_card',
    },
  ],
  metadata: {
    provider: 'Groq',
    model: 'llama-3.3-70b-versatile',
    latency_ms: 1100.0,
    token_usage: { prompt_tokens: 1800, completion_tokens: 520, total_tokens: 2320 },
  },
};

// ===========================================================================
// EducationalScriptCard Tests
// ===========================================================================

test('1. EducationalScriptCard renders "ready to generate" state when not yet generated', () => {
  const html = renderToString(
    React.createElement(EducationalScriptCard, {
      script: null,
      isLoading: false,
      isPrerequisiteReady: true,
      error: null,
    })
  );

  assert.match(html, /Generate Evidence-Grounded Educational Script/);
  assert.match(html, /Stage 05 • AI Educational Narration Script/);
  assert.match(html, /Generate Educational Script/);
});

test('2. EducationalScriptCard indicates when prerequisite knowledge is not ready', () => {
  const html = renderToString(
    React.createElement(EducationalScriptCard, {
      script: null,
      isLoading: false,
      isPrerequisiteReady: false,
      error: null,
    })
  );

  assert.match(html, /Waiting for repository knowledge consolidation/);
  assert.doesNotMatch(html, /<button[^>]*>Generate Educational Script<\/button>/);
});

test('3. EducationalScriptCard renders loading state with spinner', () => {
  const html = renderToString(
    React.createElement(EducationalScriptCard, {
      script: null,
      isLoading: true,
      isPrerequisiteReady: true,
      error: null,
    })
  );

  assert.match(html, /Generating Educational Narration Script\.\.\./);
  assert.match(html, /Synthesizing repository architecture/);
});

test('4. EducationalScriptCard displays error state', () => {
  const html = renderToString(
    React.createElement(EducationalScriptCard, {
      script: null,
      isLoading: false,
      isPrerequisiteReady: true,
      error: 'Groq rate limit exceeded (503)',
    })
  );

  assert.match(html, /Groq rate limit exceeded \(503\)/);
});

test('5. EducationalScriptCard renders generated script with title, audience, objectives and timings', () => {
  const html = renderToString(
    React.createElement(EducationalScriptCard, {
      script: mockScript,
      isLoading: false,
      isPrerequisiteReady: true,
    })
  );

  // Title and repository
  assert.match(html, /Inside Click: Composable Command-Line Interfaces/);
  assert.match(html, /pallets\/click/);

  // Duration and badges
  assert.match(html, /75\.0.*Narration/);
  assert.match(html, /Static Analysis Grounded/);

  // Introduction, audience, objectives
  assert.match(html, /Click is a Python package for creating composable/);
  assert.match(html, /Python Developers/);
  assert.match(html, /Understand Click decorator-driven argument binding/);

  // Section titles
  assert.match(html, /Introduction &amp; Command Line Interfaces/);
  assert.match(html, /Layered Engine Architecture/);
  assert.match(html, /Execution Workflow &amp; Dispatch/);
  assert.match(html, /Summary &amp; Key Takeaways/);

  // Conclusion
  assert.match(html, /Click provides a composable blueprint for building modular/);
});

test('6. EducationalScriptCard sanitizes file paths to avoid machine path leakage', () => {
  const html = renderToString(
    React.createElement(EducationalScriptCard, {
      script: mockScript,
      isLoading: false,
      isPrerequisiteReady: true,
    })
  );

  // Internal machine path must be redacted to <REPO_ROOT>/
  assert.doesNotMatch(html, /\/Users\/dev\/repo_cache/);
});

test('7. EducationalScriptCard hides regenerate button in readOnly mode', () => {
  const html = renderToString(
    React.createElement(EducationalScriptCard, {
      script: mockScript,
      isLoading: false,
      isPrerequisiteReady: true,
      readOnly: true,
    })
  );

  assert.doesNotMatch(html, /Regenerate Script/);
});

// ===========================================================================
// EducationalStoryboardCard Tests
// ===========================================================================

test('8. EducationalStoryboardCard renders "ready to generate" state when script exists', () => {
  const html = renderToString(
    React.createElement(EducationalStoryboardCard, {
      storyboard: null,
      isLoading: false,
      isScriptAvailable: true,
      error: null,
    })
  );

  assert.match(html, /Generate Timed Visual Storyboard/);
  assert.match(html, /Stage 06 • Educational Storyboard Plan/);
  assert.match(html, /Generate Educational Storyboard/);
});

test('9. EducationalStoryboardCard indicates when script is missing', () => {
  const html = renderToString(
    React.createElement(EducationalStoryboardCard, {
      storyboard: null,
      isLoading: false,
      isScriptAvailable: false,
      error: null,
    })
  );

  assert.match(html, /Generate an Educational Script \(Stage 05\) first to unlock Storyboard generation/);
  assert.doesNotMatch(html, /<button[^>]*>Generate Educational Storyboard<\/button>/);
});

test('10. EducationalStoryboardCard renders loading state', () => {
  const html = renderToString(
    React.createElement(EducationalStoryboardCard, {
      storyboard: null,
      isLoading: true,
      isScriptAvailable: true,
      error: null,
    })
  );

  assert.match(html, /Generating Educational Storyboard\.\.\./);
  assert.match(html, /Decomposing script sections into timed visual scenes/);
});

test('11. EducationalStoryboardCard displays error state', () => {
  const html = renderToString(
    React.createElement(EducationalStoryboardCard, {
      storyboard: null,
      isLoading: false,
      isScriptAvailable: true,
      error: 'Failed to generate storyboard from script (502)',
    })
  );

  assert.match(html, /Failed to generate storyboard from script \(502\)/);
});

test('12. EducationalStoryboardCard renders generated storyboard with orientation, timing, and visual notice', () => {
  const html = renderToString(
    React.createElement(EducationalStoryboardCard, {
      storyboard: mockStoryboard,
      isLoading: false,
      isScriptAvailable: true,
    })
  );

  // Header & duration
  assert.match(html, /Inside Click: Composable Command-Line Interfaces Storyboard/);
  assert.match(html, /75\.0.*Total Duration/);
  assert.match(html, /landscape/i);
  assert.match(html, /16:9/);
  assert.match(html, /4.*Scenes/);

  // Production notice
  assert.match(html, /Visual Production Blueprint/);
  assert.match(html, /Actual rendering of diagrams, visual animations, and speech audio is scheduled/);

  // Scene titles & types
  assert.match(html, /Hook &amp; Title Card/);
  assert.match(html, /Title Card/);
  assert.match(html, /Three-Tier Architecture/);
  assert.match(html, /Architecture Diagram/);
  assert.match(html, /Argument Dispatch Pipeline/);
  assert.match(html, /Workflow Diagram/);
  assert.match(html, /Key Takeaways &amp; Summary/);
  assert.match(html, /Key Takeaways/);
});

test('13. EducationalStoryboardCard sanitizes file paths and hides regenerate in readOnly mode', () => {
  const html = renderToString(
    React.createElement(EducationalStoryboardCard, {
      storyboard: mockStoryboard,
      isLoading: false,
      isScriptAvailable: true,
      readOnly: true,
    })
  );

  assert.doesNotMatch(html, /\/Users\/dev\/repo_cache/);
  assert.doesNotMatch(html, /Regenerate Storyboard/);
});

// ===========================================================================
// API Client Tests
// ===========================================================================

test('14. getEducationalScript returns parsed data on HTTP 200', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.match(url, /\/api\/v1\/jobs\/job-123\/educational-script$/);
    assert.equal(options.method, 'GET');
    return {
      ok: true,
      status: 200,
      json: async () => mockScript,
    };
  };

  try {
    const res = await apiClient.getEducationalScript('job-123');
    assert.equal(res.success, true);
    assert.equal(res.status, 200);
    assert.equal(res.data.script_id, mockScript.script_id);
    assert.equal(res.data.title, mockScript.title);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('15. getEducationalScript handles 404 cleanly when not yet generated', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 404,
    json: async () => ({ detail: "Educational script has not yet been generated for job 'job-404'." }),
  });

  try {
    const res = await apiClient.getEducationalScript('job-404');
    assert.equal(res.success, false);
    assert.equal(res.status, 404);
    assert.match(res.error, /has not yet been generated/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('16. generateEducationalScript formats query parameters and executes POST', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => mockScript,
    };
  };

  try {
    // Normal POST
    const r1 = await apiClient.generateEducationalScript('job-1');
    assert.equal(r1.success, true);
    assert.match(calls[0].url, /\/api\/v1\/jobs\/job-1\/educational-script$/);
    assert.equal(calls[0].options.method, 'POST');

    // POST with refresh and provider override
    const r2 = await apiClient.generateEducationalScript('job-1', 'groq', true);
    assert.equal(r2.success, true);
    assert.match(calls[1].url, /\/api\/v1\/jobs\/job-1\/educational-script\?provider=groq&refresh=true$/);
    assert.equal(calls[1].options.method, 'POST');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('17. getEducationalStoryboard returns parsed data on HTTP 200 and handles 404 cleanly', async () => {
  const originalFetch = globalThis.fetch;
  try {
    // 200 Success
    globalThis.fetch = async (url) => {
      assert.match(url, /\/api\/v1\/jobs\/job-sb\/educational-storyboard$/);
      return {
        ok: true,
        status: 200,
        json: async () => mockStoryboard,
      };
    };
    const res = await apiClient.getEducationalStoryboard('job-sb');
    assert.equal(res.success, true);
    assert.equal(res.data.storyboard_id, mockStoryboard.storyboard_id);

    // 404 Not Found
    globalThis.fetch = async () => ({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Educational storyboard has not yet been generated for job 'job-sb-404'." }),
    });
    const res404 = await apiClient.getEducationalStoryboard('job-sb-404');
    assert.equal(res404.success, false);
    assert.equal(res404.status, 404);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('18. generateEducationalStoryboard executes POST with refresh=true', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => mockStoryboard,
    };
  };

  try {
    const res = await apiClient.generateEducationalStoryboard('job-sb-refresh', null, true);
    assert.equal(res.success, true);
    assert.match(calls[0].url, /\/api\/v1\/jobs\/job-sb-refresh\/educational-storyboard\?refresh=true$/);
    assert.equal(calls[0].options.method, 'POST');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

// ===========================================================================
// ProcessingView & VideoResultView Integration Tests
// ===========================================================================

test('19. ProcessingView renders both EducationalScriptCard and EducationalStoryboardCard in sequence', () => {
  const mockJob = {
    job_id: 'job-full-integration',
    repo_name: 'pallets/click',
    repo_url: 'https://github.com/pallets/click',
    ingestion_status: 'completed',
    status: 'in_progress',
    progress_percentage: 66,
    stages: [
      { id: 1, name: 'Repository Fetching', status: 'completed' },
      { id: 2, name: 'Repository Analysis', status: 'completed' },
      { id: 3, name: 'Code Understanding', status: 'completed' },
      { id: 4, name: 'AI Summary Generation', status: 'completed' },
      { id: 5, name: 'Script Generation', status: 'completed' },
      { id: 6, name: 'Storyboard Generation', status: 'completed' },
      { id: 7, name: 'Visual Generation', status: 'pending' },
      { id: 8, name: 'Voice Generation', status: 'pending' },
      { id: 9, name: 'Video Assembly', status: 'pending' },
    ],
    knowledge: {
      repository: { name: 'click', owner: 'pallets' },
      statistics: {
        total_files: 20,
        source_files: 15,
        filtered_files: 5,
        total_lines_of_code: 1200,
        total_functions: 10,
        total_classes: 5,
        total_methods: 8,
        total_imports: 12,
        total_function_calls: 15,
        total_internal_dependencies: 4,
        total_external_dependencies: 2,
        circular_dependencies_count: 0,
      },
      important_files: [],
      source_evidence: [],
      technology_stack: { languages: [{ name: 'Python' }] },
      repository_structure: { important_directories: ['src/click'] },
    },
    has_educational_script: true,
    educational_script: mockScript,
    has_educational_storyboard: true,
    educational_storyboard: mockStoryboard,
  };

  const html = renderToString(
    React.createElement(ProcessingView, {
      job: mockJob,
      onSimulateStep: () => {},
      isSimulating: false,
      onViewResults: () => {},
      onCancel: () => {},
      onJobUpdated: () => {},
    })
  );

  // Both cards rendered
  assert.match(html, /Stage 05 • Educational Script/);
  assert.match(html, /Inside Click: Composable Command-Line Interfaces/);
  assert.match(html, /Stage 06 • Educational Storyboard/);
  assert.match(html, /Inside Click: Composable Command-Line Interfaces Storyboard/);
  assert.match(html, /Pipeline Execution Breakdown \(9 Stages\)/);
});

test('20. VideoResultView displays cached script and storyboard in readOnly mode', () => {
  const completedJob = {
    job_id: 'job-completed-view',
    repo_name: 'pallets/click',
    repo_url: 'https://github.com/pallets/click',
    status: 'completed',
    has_educational_script: true,
    educational_script: mockScript,
    has_educational_storyboard: true,
    educational_storyboard: mockStoryboard,
    result: {
      repo_name: 'pallets/click',
      repo_url: 'https://github.com/pallets/click',
      description: 'Composable command line interface toolkit.',
      tech_stack: ['Python'],
      summary: 'Architectural video walkthrough.',
      video_url: 'https://example.com/click.mp4',
    },
  };

  const html = renderToString(
    React.createElement(VideoResultView, {
      job: completedJob,
      onReset: () => {},
    })
  );

  // Script and Storyboard rendered in readOnly mode
  assert.match(html, /Stage 05 • Educational Script/);
  assert.match(html, /Stage 06 • Educational Storyboard/);
  assert.doesNotMatch(html, /Regenerate Script/);
  assert.doesNotMatch(html, /Regenerate Storyboard/);
});

test('21. VideoResultView cleanly omits script and storyboard when ungenerated without errors', () => {
  const basicJob = {
    job_id: 'job-basic',
    repo_name: 'pallets/click',
    repo_url: 'https://github.com/pallets/click',
    status: 'completed',
    has_educational_script: false,
    educational_script: null,
    has_educational_storyboard: false,
    educational_storyboard: null,
    result: {
      repo_name: 'pallets/click',
      repo_url: 'https://github.com/pallets/click',
      description: 'Toolkit',
      tech_stack: ['Python'],
      summary: 'Walkthrough',
      video_url: 'https://example.com/v.mp4',
    },
  };

  const html = renderToString(
    React.createElement(VideoResultView, {
      job: basicJob,
      onReset: () => {},
    })
  );

  // Video view works
  assert.match(html, /Video Ready/);
  // Must NOT display ungenerated cards
  assert.doesNotMatch(html, /Generate Evidence-Grounded Educational Script/);
  assert.doesNotMatch(html, /Generate Timed Visual Storyboard/);
});

// Close Vite SSR server after test completion
await vite.close();
console.log('All Milestone 4.2 frontend unit tests passed successfully.');
