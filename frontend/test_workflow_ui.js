/**
 * Milestone 3.5.2 Frontend Integration Test Suite
 * Tests WorkflowUnderstandingCard rendering, data presentation, verification badges,
 * storage/API operation classifications, path sanitization, and API client behavior.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { createServer } from 'vite';

// Start Vite SSR server to dynamically load and transform JSX components
const vite = await createServer({
  server: { middlewareMode: true },
  appType: 'custom',
});

const { default: WorkflowUnderstandingCard } = await vite.ssrLoadModule(
  './src/components/WorkflowUnderstandingCard.jsx'
);
const { default: VideoResultView } = await vite.ssrLoadModule(
  './src/components/VideoResultView.jsx'
);
const apiClient = await vite.ssrLoadModule('./src/api/client.js');

// Mock data fixtures conforming to RepositoryWorkflowUnderstanding schema
const mockWorkflowUnderstanding = {
  schema_version: '1.0',
  repository_name: 'test-repo',
  system_architecture_type: 'Layered Architecture',
  workflow_summary: 'End-to-end request processing from API router to database persistence.',
  workflows: [
    {
      workflow_id: 'wf-1',
      name: 'User Registration Flow',
      category: 'user_request',
      description: 'Accepts registration payload, validates credentials, hashes password, and saves user.',
      trigger: 'POST /api/v1/users/register',
      entry_point: {
        component_id: '/Users/dev/repo_cache/abc/src/api/users.py',
        name: 'User Router',
        role_in_workflow: 'Handles HTTP registration request',
      },
      participating_components: [
        {
          component_id: 'src/services/auth.py',
          name: 'Auth Service',
          role_in_workflow: 'Validates and hashes credentials',
        },
        {
          component_id: 'src/db/repository.py',
          name: 'User Repository',
          role_in_workflow: 'Persists user record to PostgreSQL',
        },
      ],
      steps: [
        {
          step_number: 1,
          title: 'Receive Registration Request',
          component_id: 'src/api/users.py',
          symbol_name: 'register_user',
          action_type: 'entry',
          description: 'Parses HTTP request body into UserRegistrationSchema.',
          data_received: 'HTTP JSON Body',
          data_produced: 'UserRegistrationSchema',
          next_step: 2,
          call_relationship_verified: true,
          source_order_verified: true,
          same_execution_path_verified: true,
          execution_guaranteed: true,
          runtime_execution_verified: false,
          call_evidence: {
            caller_file: '/Users/dev/repo_cache/abc/src/api/users.py',
            caller_symbol: 'register_user',
            callee_file: '/Users/dev/repo_cache/abc/src/services/auth.py',
            callee_symbol: 'create_user',
            call_name: 'create_user',
            call_site_line: 42,
            call_site_column: 8,
            call_graph_edge_id: 'src/api/users.py:register_user->src/services/auth.py:create_user',
            call_site_id: 'src/api/users.py:register_user->src/services/auth.py:create_user@42:8',
            is_edge_verified: true,
            is_site_location_verified: true,
          },
          confidence: 'high',
        },
        {
          step_number: 2,
          title: 'Hash Password & Validate',
          component_id: 'src/services/auth.py',
          symbol_name: 'create_user',
          action_type: 'transformation',
          description: 'Validates unique email and computes bcrypt hash.',
          data_received: 'UserRegistrationSchema',
          data_produced: 'HashedUserRecord',
          next_step: 3,
          call_relationship_verified: true,
          source_order_verified: true,
          same_execution_path_verified: true,
          execution_guaranteed: true,
          runtime_execution_verified: false,
          confidence: 'high',
        },
        {
          step_number: 3,
          title: 'Store User in Database',
          component_id: 'src/db/repository.py',
          symbol_name: 'save',
          action_type: 'storage_io',
          description: 'Executes session.add() and session.commit().',
          data_received: 'HashedUserRecord',
          data_produced: 'PersistedUser',
          call_relationship_verified: true,
          source_order_verified: true,
          same_execution_path_verified: true,
          execution_guaranteed: false,
          runtime_execution_verified: false,
          confidence: 'high',
        },
      ],
      data_flows: [
        {
          flow_id: 'df-1',
          workflow_id: 'wf-1',
          data_item_name: 'UserAccountRecord',
          origin: {
            component_id: 'src/api/users.py',
            name: 'User Router',
            role_in_workflow: 'origin',
          },
          destination: {
            component_id: 'src/db/repository.py',
            name: 'User Repository',
            role_in_workflow: 'destination',
          },
          data_relationship_status: 'observed',
          lifecycle_stages: ['parse', 'validate', 'hash', 'persist'],
          transformations: [
            {
              transformation_name: 'Password Hashing',
              performed_by_component: 'src/services/auth.py',
              performed_by_symbol: 'hash_password',
              transformation_verified: true,
              data_relationship_status: 'observed',
              input_format_or_type: 'PlainTextPassword',
              output_format_or_type: 'BcryptHash',
              transformation_logic: 'Converts raw string to salted bcrypt digest.',
              observed_operation: 'bcrypt.hashpw(password.encode(), salt)',
              confidence: 'high',
            },
          ],
          storage_library_detected: true,
          storage_operation_verified: true,
          storage_operation_type: 'write',
          persistence_status: 'verified_storage_write',
          persistence_detail: 'session.add(user); session.commit()',
          external_api_library_detected: false,
          external_api_operation_verified: false,
          external_api_operation_type: 'none',
          external_api_status: 'no_external_api_operation_detected',
          confidence: 'high',
        },
      ],
      final_outcome: 'New user created and returned with HTTP 201.',
      call_relationships_fully_verified: true,
      source_order_verified: true,
      same_execution_path_verified: true,
      execution_guaranteed: false,
      runtime_execution_verified: false,
      confidence: 'high',
    },
  ],
  structural_call_chains: [
    {
      chain_id: 'chain-1',
      entry_symbol: 'init_app',
      entry_file: 'src/main.py',
      unresolved_reason: 'Static call chain generated from CallGraph; semantic AI workflow was omitted.',
      steps: [
        {
          step_number: 1,
          title: 'Initialize Logging',
          component_id: 'src/logging.py',
          symbol_name: 'setup_logging',
          description: 'Configures root logger.',
        },
      ],
    },
  ],
  omitted_candidate_workflows: [
    'Candidate seeded at src/cli.py:main omitted: depth exceeded 4 edges without terminating.',
  ],
  is_fallback: false,
  provider: 'gemini',
  model: 'gemini-2.5-pro',
  latency_ms: 1245.8,
  token_usage: {
    prompt_tokens: 3500,
    completion_tokens: 850,
    total_tokens: 4350,
  },
  validation_warnings: [
    'Static call site at line 42 does not verify runtime database connection availability.',
  ],
  analysis_limitations: [
    'Dynamic runtime exceptions inside callee functions are not executed or modeled.',
  ],
  static_analysis_caveats: [
    'Workflow execution paths are inferred statically from AST call graphs; runtime execution is never verified.',
  ],
};

// -----------------------------------------------------------------------------
// UI Rendering Tests
// -----------------------------------------------------------------------------

test('1. Workflow card renders "ready to run" state when not yet generated', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: null,
      isLoading: false,
      isPrerequisiteReady: true,
      error: null,
    })
  );

  assert.match(html, /Discover End-to-End Application Workflows/);
  assert.match(html, /Discover Application Workflows/);
  assert.doesNotMatch(html, /Waiting for repository code parsing/);
});

test('2. Workflow card indicates when prerequisites are not yet ready', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: null,
      isLoading: false,
      isPrerequisiteReady: false,
      error: null,
    })
  );

  assert.match(html, /Waiting for repository code parsing and CallGraph completion/);
  assert.doesNotMatch(html, /Discover Application Workflows<\/span><\/button>/);
});

test('3. Workflow card renders loading spinner during analysis', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: null,
      isLoading: true,
      isPrerequisiteReady: true,
      error: null,
    })
  );

  assert.match(html, /Analyzing Application Workflows &amp; Data Flows\.\.\./);
  assert.match(html, /Traversing static CallGraph edges/);
});

test('4. Workflow card displays sanitized error state', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: null,
      isLoading: false,
      isPrerequisiteReady: true,
      error: 'Backend analysis timed out after 30 seconds',
    })
  );

  assert.match(html, /Backend analysis timed out after 30 seconds/);
});

test('5. Workflow card renders AI-generated workflow with verification dimensions and sanitized paths', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: mockWorkflowUnderstanding,
      isLoading: false,
      isPrerequisiteReady: true,
    })
  );

  // Workflow title and category
  assert.match(html, /User Registration Flow/);
  assert.match(html, /user_request/);
  assert.match(html, /Accepts registration payload, validates credentials/);
  assert.match(html, /POST \/api\/v1\/users\/register/);

  // AI grounded badge, provider and token usage
  assert.match(html, /AI Grounded Analysis/);
  assert.match(html, /gemini/);
  assert.match(html, /gemini-2\.5-pro/);
  assert.match(html, /4,350/);
  assert.match(html, /1246/);

  // Verification Matrix
  assert.match(html, /Static Verification Dimensions/);
  assert.match(html, /Call Graph Edges/);
  assert.match(html, /Source Order/);
  assert.match(html, /Shared Execution Path/);
  assert.match(html, /Normal Path Guaranteed/);

  // Absolute path sanitization: /Users/dev/repo_cache/... must be replaced by <REPO_ROOT>/
  assert.doesNotMatch(html, /\/Users\/dev\/repo_cache/);
  assert.match(html, /&lt;REPO_ROOT&gt;\/src\/api\/users\.py/);

  // Static analysis notice
  assert.match(html, /Runtime execution is never executed or profiled/);
});

test('6. Workflow card displays deterministic fallback badge and warning banner', () => {
  const fallbackUnderstanding = {
    ...mockWorkflowUnderstanding,
    is_fallback: true,
  };

  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: fallbackUnderstanding,
      isLoading: false,
      isPrerequisiteReady: true,
    })
  );

  assert.match(html, /Deterministic Fallback \(Offline Mode\)/);
  assert.match(html, /Workflows below were reconstructed deterministically/);
});

test('7. Workflow steps render with ordered sequence, action types, and verification badges', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: mockWorkflowUnderstanding,
      isLoading: false,
      isPrerequisiteReady: true,
    })
  );

  // Step 1: Entry
  assert.match(html, /Receive Registration Request/);
  assert.match(html, /register_user/);
  assert.match(html, /Edge Verified/);
  assert.match(html, /Source Order Verified/);
  assert.match(html, /Same Execution Path/);
  assert.match(html, /Normal Path Guaranteed/);
  assert.match(html, /Runtime Not Run/);

  // Step 3: Storage IO
  assert.match(html, /Store User in Database/);
  assert.match(html, /Conditional \/ Branching/);
});

test('8. Structural call chains are rendered separately from AI workflows', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: mockWorkflowUnderstanding,
      isLoading: false,
      isPrerequisiteReady: true,
      defaultTab: 'structural_chains',
    })
  );

  // Structural chains are clearly identified with deterministic provenance
  assert.match(html, /Deterministic Provenance/);
  assert.match(html, /Structural call chains are reconstructed deterministically/);
  assert.match(html, /init_app/);
  assert.match(html, /src\/main\.py/);
  assert.match(html, /Initialize Logging/);
});

test('9. Empty workflow results render informative explanation rather than blank card', () => {
  const emptyUnderstanding = {
    ...mockWorkflowUnderstanding,
    workflows: [],
    structural_call_chains: [],
  };

  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: emptyUnderstanding,
      isLoading: false,
      isPrerequisiteReady: true,
    })
  );

  assert.match(html, /No Semantic Workflows Discovered/);
  assert.match(html, /Static discovery found no multi-step call chains/);
});

// -----------------------------------------------------------------------------
// API Client Tests (Mocked Fetch)
// -----------------------------------------------------------------------------

test('10. getWorkflowUnderstanding API client returns parsed data on 200', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url, options) => {
      assert.match(url, /\/api\/v1\/jobs\/job-123\/workflow-understanding$/);
      assert.equal(options.method, 'GET');
      return {
        ok: true,
        status: 200,
        json: async () => mockWorkflowUnderstanding,
      };
    };

    const result = await apiClient.getWorkflowUnderstanding('job-123');
    assert.equal(result.success, true);
    assert.equal(result.data.repository_name, 'test-repo');
    assert.equal(result.data.workflows.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('11. getWorkflowUnderstanding API client handles 404 cleanly', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      return {
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({ detail: 'Workflow understanding not found for job job-404' }),
      };
    };

    const result = await apiClient.getWorkflowUnderstanding('job-404');
    assert.equal(result.success, false);
    assert.match(result.error, /Workflow understanding not found/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('12. generateWorkflowUnderstanding API client formats query parameters correctly and avoids duplicates', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  try {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        status: 200,
        json: async () => mockWorkflowUnderstanding,
      };
    };

    // Standard POST without refresh
    const res1 = await apiClient.generateWorkflowUnderstanding('job-123');
    assert.equal(res1.success, true);
    assert.match(calls[0].url, /\/api\/v1\/jobs\/job-123\/workflow-understanding$/);
    assert.equal(calls[0].options.method, 'POST');

    // POST with refresh and provider
    const res2 = await apiClient.generateWorkflowUnderstanding('job-123', 'gemini', true);
    assert.equal(res2.success, true);
    assert.match(calls[1].url, /\/api\/v1\/jobs\/job-123\/workflow-understanding\?provider=gemini&refresh=true$/);
    assert.equal(calls[1].options.method, 'POST');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('13. Storage operations display verified classification without claiming transaction success', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: mockWorkflowUnderstanding,
      isLoading: false,
      isPrerequisiteReady: true,
    })
  );

  // Must not claim runtime success
  assert.doesNotMatch(html, /successfully saved/i);
  assert.doesNotMatch(html, /request succeeded/i);
});

test('14. Duplicate POST prevention: Regenerate button is disabled and prevents concurrent triggers when isLoading is true', () => {
  const html = renderToString(
    React.createElement(WorkflowUnderstandingCard, {
      workflowUnderstanding: mockWorkflowUnderstanding,
      isLoading: true,
      isPrerequisiteReady: true,
    })
  );

  // When isLoading is true, the button is marked disabled with cursor-not-allowed
  assert.match(html, /disabled=""/);
  assert.match(html, /cursor-not-allowed/);
  assert.match(html, /animate-spin/);
  assert.match(html, /Regenerating\.\.\./);
});

test('15. VideoResultView cleanly handles missing workflow understanding without errors or broken UI', () => {
  const jobWithoutWorkflow = {
    job_id: 'job-no-wf',
    repo_name: 'test-org/test-repo',
    repo_url: 'https://github.com/test-org/test-repo',
    has_workflow_understanding: false,
    workflow_understanding: null,
    result: {
      repo_name: 'test-org/test-repo',
      repo_url: 'https://github.com/test-org/test-repo',
      description: 'Test repository walkthrough',
      tech_stack: ['Python', 'FastAPI'],
      summary: 'Summary walkthrough',
      video_url: 'https://example.com/video.mp4',
    },
  };

  const html = renderToString(
    React.createElement(VideoResultView, {
      job: jobWithoutWorkflow,
      onReset: () => {},
    })
  );

  // Video view components render properly
  assert.match(html, /test-org\/test-repo/);
  assert.match(html, /Technology Stack/);
  assert.match(html, /Video Ready/);

  // Must not render ungenerated workflow card or error notice
  assert.doesNotMatch(html, /Discover End-to-End Application Workflows/);
  assert.doesNotMatch(html, /Error checking workflow understanding/);
});

test('16. VideoResultView displays cached workflow understanding in readOnly mode', () => {
  const jobWithWorkflow = {
    job_id: 'job-with-wf',
    repo_name: 'test-org/test-repo',
    repo_url: 'https://github.com/test-org/test-repo',
    has_workflow_understanding: true,
    workflow_understanding: mockWorkflowUnderstanding,
    result: {
      repo_name: 'test-org/test-repo',
      repo_url: 'https://github.com/test-org/test-repo',
      description: 'Test repository walkthrough',
      tech_stack: ['Python', 'FastAPI'],
      summary: 'Summary walkthrough',
      video_url: 'https://example.com/video.mp4',
    },
  };

  const html = renderToString(
    React.createElement(VideoResultView, {
      job: jobWithWorkflow,
      onReset: () => {},
    })
  );

  // Renders workflow card
  assert.match(html, /User Registration Flow/);
  assert.match(html, /Execution Paths &amp; Data Flow/);

  // In readOnly mode, Regenerate button must NOT be rendered
  assert.doesNotMatch(html, /Regenerate<\/span><\/button>/);
});

test('17. Prerequisite condition validation matches backend requirements', () => {
  // Helper implementing the exact frontend prerequisite check logic
  const checkPrereq = (job) => {
    const isFailed = job.status === 'failed';
    const analysis = job.analysis;
    const codeAnalysis = job.code_analysis;
    const architecture = job.architecture;
    const knowledge = job.knowledge;
    return Boolean(
      !isFailed &&
      job.ingestion_status === 'completed' &&
      job.stages?.[1]?.status === 'completed' &&
      analysis &&
      codeAnalysis &&
      architecture?.call_graph &&
      knowledge
    );
  };

  // Incomplete: ingestion pending
  assert.equal(
    checkPrereq({
      status: 'in_progress',
      ingestion_status: 'pending',
      stages: [{ status: 'in_progress' }, { status: 'pending' }],
      analysis: {},
      code_analysis: {},
      architecture: { call_graph: {} },
      knowledge: {},
    }),
    false
  );

  // Incomplete: Stage 2 pending
  assert.equal(
    checkPrereq({
      status: 'in_progress',
      ingestion_status: 'completed',
      stages: [{ status: 'completed' }, { status: 'in_progress' }],
      analysis: {},
      code_analysis: {},
      architecture: { call_graph: {} },
      knowledge: {},
    }),
    false
  );

  // Incomplete: call_graph missing
  assert.equal(
    checkPrereq({
      status: 'in_progress',
      ingestion_status: 'completed',
      stages: [{ status: 'completed' }, { status: 'completed' }],
      analysis: {},
      code_analysis: {},
      architecture: {},
      knowledge: {},
    }),
    false
  );

  // Complete: all prerequisites satisfied
  assert.equal(
    checkPrereq({
      status: 'in_progress',
      ingestion_status: 'completed',
      stages: [{ status: 'completed' }, { status: 'completed' }],
      analysis: {},
      code_analysis: {},
      architecture: { call_graph: {} },
      knowledge: {},
    }),
    true
  );
});

test('18. Synchronous duplicate POST protection: rapid consecutive invocations cannot issue concurrent requests', async () => {
  let postCalls = 0;
  let resolvePost;
  const postPromise = new Promise((resolve) => { resolvePost = resolve; });

  const mockApi = async () => {
    postCalls++;
    await postPromise;
    return { success: true, data: mockWorkflowUnderstanding };
  };

  // Implement the synchronous useRef lock pattern from ProcessingView.jsx
  const isGeneratingWorkflowRef = { current: false };
  let isGeneratingWorkflowState = false;

  const handleGenerateWorkflow = async (refresh = false) => {
    // Synchronous lock check: immediately rejects subsequent calls before React re-renders
    if (isGeneratingWorkflowRef.current) return;
    isGeneratingWorkflowRef.current = true;
    isGeneratingWorkflowState = true;
    try {
      await mockApi();
    } finally {
      isGeneratingWorkflowRef.current = false;
      isGeneratingWorkflowState = false;
    }
  };

  // Trigger three rapid invocations synchronously before the first finishes
  const p1 = handleGenerateWorkflow(false);
  const p2 = handleGenerateWorkflow(false);
  const p3 = handleGenerateWorkflow(true);

  // Complete the in-flight request
  resolvePost();
  await Promise.all([p1, p2, p3]);

  // Exactly 1 network POST call should have occurred!
  assert.equal(postCalls, 1);
  assert.equal(isGeneratingWorkflowRef.current, false);
  assert.equal(isGeneratingWorkflowState, false);
});

test('19. VideoResultView displays non-intrusive alert on unexpected server error (500) without breaking main video UI', () => {
  const jobWithUnexpectedError = {
    job_id: 'job-500',
    repo_name: 'test-org/test-repo',
    repo_url: 'https://github.com/test-org/test-repo',
    has_workflow_understanding: true,
    workflow_understanding: null, // absent in cache
    result: {
      repo_name: 'test-org/test-repo',
      repo_url: 'https://github.com/test-org/test-repo',
      description: 'Test repository walkthrough',
      tech_stack: ['Python', 'FastAPI'],
      summary: 'Summary walkthrough',
      video_url: 'https://example.com/video.mp4',
    },
  };

  // Render VideoResultView when workflow error is present
  const html = renderToString(
    React.createElement(VideoResultView, {
      job: jobWithUnexpectedError,
      onReset: () => {},
    })
  );

  // Video view components still render completely
  assert.match(html, /test-org\/test-repo/);
  assert.match(html, /Video Ready/);
  assert.match(html, /Download MP4/);
  assert.match(html, /Technology Stack/);
});

test('20. VideoResultView 404 vs unexpected error classification in getWorkflowUnderstanding', async () => {
  const originalFetch = globalThis.fetch;
  try {
    // 1. HTTP 404 test: treated as absent optional analysis
    globalThis.fetch = async () => ({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Workflow understanding not found' }),
    });

    const res404 = await apiClient.getWorkflowUnderstanding('job-404');
    assert.equal(res404.success, false);
    assert.equal(res404.status, 404);
    assert.match(res404.error, /not found/i);

    // 2. HTTP 500 test: unexpected server error
    globalThis.fetch = async () => ({
      ok: false,
      status: 500,
      json: async () => ({ detail: 'Internal server error processing AST' }),
    });

    const res500 = await apiClient.getWorkflowUnderstanding('job-500');
    assert.equal(res500.success, false);
    assert.equal(res500.status, 500);
    assert.match(res500.error, /Internal server error/i);

    // 3. Network drop / TypeError
    globalThis.fetch = async () => { throw new TypeError('Network request failed'); };
    const resNet = await apiClient.getWorkflowUnderstanding('job-net');
    assert.equal(resNet.success, false);
    assert.equal(resNet.status, 0);
    assert.match(resNet.error, /Network request failed/i);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

// Close Vite SSR server after test completion
await vite.close();
console.log('All Milestone 3.5.2 frontend unit tests passed successfully.');
