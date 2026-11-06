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

export async function getJobKnowledge(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/knowledge`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to fetch repository knowledge (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error checking repository knowledge',
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

export async function getProjectUnderstanding(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/project-understanding`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to fetch project understanding (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error checking project understanding',
    };
  }
}

export async function generateProjectUnderstanding(jobId, provider = null, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (provider) params.append('provider', provider);
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/project-understanding${queryString}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to generate project understanding (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error generating project understanding',
    };
  }
}

export async function getCodeUnderstanding(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/code-understanding`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to fetch code understanding (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error checking code understanding',
    };
  }
}

export async function generateCodeUnderstanding(jobId, provider = null, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (provider) params.append('provider', provider);
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/code-understanding${queryString}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Failed to generate code understanding (${response.status})`);
    }

    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error.message || 'Error generating code understanding',
    };
  }
}

export async function getWorkflowUnderstanding(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/workflow-understanding`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: data.detail || `Failed to fetch workflow understanding (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking workflow understanding',
    };
  }
}

export async function generateWorkflowUnderstanding(jobId, provider = null, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (provider) params.append('provider', provider);
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/workflow-understanding${queryString}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: data.detail || `Failed to generate workflow understanding (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error generating workflow understanding',
    };
  }
}

export async function getEducationalScript(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/educational-script`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: data.detail || `Failed to fetch educational script (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking educational script',
    };
  }
}

export async function generateEducationalScript(jobId, provider = null, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (provider) params.append('provider', provider);
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/educational-script${queryString}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: data.detail || `Failed to generate educational script (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error generating educational script',
    };
  }
}

export async function getEducationalStoryboard(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/educational-storyboard`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: data.detail || `Failed to fetch educational storyboard (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking educational storyboard',
    };
  }
}

export async function generateEducationalStoryboard(jobId, provider = null, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (provider) params.append('provider', provider);
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/educational-storyboard${queryString}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = {};
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: data.detail || `Failed to generate educational storyboard (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error generating educational storyboard',
    };
  }
}
