/**
 * API client for RepoGenie backend communication.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export async function checkBackendHealth() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/health`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP error ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Unable to connect to RepoGenie backend',
    };
  }
}

export async function createJob(githubUrl) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({ github_url: githubUrl }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to create job (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error submitting repository',
    };
  }
}

export async function getJobStatus(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to fetch job (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error checking job status',
    };
  }
}

export async function getJobAnalysis(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/analysis`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to fetch repository analysis (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error checking repository analysis',
    };
  }
}

export async function getJobCodeAnalysis(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/code-analysis`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to fetch code analysis (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error checking code analysis',
    };
  }
}

export async function getJobArchitecture(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/architecture`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to fetch architecture analysis (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error checking architecture analysis',
    };
  }
}

export async function simulateJobStep(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/simulate-step`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to advance job step (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error simulating job step',
    };
  }
}
