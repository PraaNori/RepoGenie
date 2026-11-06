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

export function getNarrationAudioUrl(jobId, assetId) {
  return `${API_BASE_URL}/api/v1/jobs/${jobId}/narration/${assetId}/file`;
}

export async function getNarration(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/narration`, {
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
        error: data.detail || `Failed to fetch narration audio (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking narration audio',
    };
  }
}

export async function generateNarration(jobId, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/narration${queryString}`, {
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
        error: data.detail || `Failed to generate narration audio (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error generating narration audio',
    };
  }
}

export function getCaptionFileUrl(jobId, assetId = 'full', format = 'srt') {
  return `${API_BASE_URL}/api/v1/jobs/${jobId}/captions/${assetId}/file?format=${encodeURIComponent(format)}`;
}

export async function getCaptions(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/captions`, {
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
        error: data.detail || `Failed to fetch captions (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking captions',
    };
  }
}

export async function generateCaptions(jobId, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/captions${queryString}`, {
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
        error: data.detail || `Failed to generate captions (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error generating captions',
    };
  }
}

export async function getAssemblyInput(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/assembly-input`, {
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
        error: data.detail || `Failed to fetch assembly input package (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking assembly input package',
    };
  }
}

export async function generateAssemblyInput(jobId, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/assembly-input${queryString}`, {
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
        error: data.detail || `Failed to generate assembly input package (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error compiling assembly input package',
    };
  }
}

export async function getAssemblyReadiness(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/assembly-readiness`, {
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
        error: data.detail || `Failed to fetch assembly readiness report (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking assembly readiness report',
    };
  }
}

export async function getVideoSystemStatus(refresh = false) {
  try {
    const params = new URLSearchParams();
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/video/status${queryString}`, {
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
        error: data.detail || `Failed to fetch video system status (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking video system status',
    };
  }
}

export async function getJobRenderConfig(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/render-config`, {
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
        error: data.detail || `Failed to fetch render configuration (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking render configuration',
    };
  }
}

export async function updateJobRenderConfig(jobId, config) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/render-config`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(config),
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
        error: data.detail || `Failed to update render configuration (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error updating render configuration',
    };
  }
}

export async function getJobRender(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/render`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to fetch render status (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking render status',
    };
  }
}

// ==============================================================================
// Milestone 6.2: Scene Video Rendering API Client Methods
// ==============================================================================

export async function getSceneRenders(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/render-scenes`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to fetch scene renders (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking scene renders',
    };
  }
}

export async function renderScenes(jobId, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/render-scenes${queryString}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to render scenes (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error executing scene rendering',
    };
  }
}

export async function getSingleSceneRender(jobId, sceneId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/render-scenes/${sceneId}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to fetch scene ${sceneId} (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || `Error checking scene ${sceneId}`,
    };
  }
}

export function getSceneRenderFileUrl(jobId, sceneId) {
  return `${API_BASE_URL}/api/v1/jobs/${jobId}/render-scenes/${sceneId}/file`;
}

// ==============================================================================
// Milestone 6.3: Final Video Assembly API Client Methods
// ==============================================================================

export async function assembleFinalVideo(jobId, refresh = false) {
  try {
    const params = new URLSearchParams();
    if (refresh) params.append('refresh', 'true');
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/assemble-video${queryString}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to assemble final video (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error executing final video assembly',
    };
  }
}

export async function getFinalVideoResult(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/render-result`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to fetch final video result (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error checking final video result',
    };
  }
}

export function getFinalVideoFileUrl(jobId) {
  return `${API_BASE_URL}/api/v1/jobs/${jobId}/video/file`;
}

export async function getVisualAssets(jobId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/visual-assets`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to fetch visual assets (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error fetching visual assets',
    };
  }
}

export async function generateVisualAssets(jobId, refresh = false) {
  try {
    const url = new URL(`${API_BASE_URL}/api/v1/jobs/${jobId}/visual-assets`);
    if (refresh) {
      url.searchParams.set('refresh', 'true');
    }

    const response = await fetch(url.toString(), {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to generate visual assets (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error generating visual assets',
    };
  }
}

export function getVisualAssetFileUrl(jobId, assetId) {
  return `${API_BASE_URL}/api/v1/jobs/${jobId}/visual-assets/${assetId}/file`;
}

export async function runFullPipeline(jobId, refresh = false) {
  try {
    const url = new URL(`${API_BASE_URL}/api/v1/jobs/${jobId}/run-pipeline`);
    if (refresh) {
      url.searchParams.set('refresh', 'true');
    }

    const response = await fetch(url.toString(), {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to start pipeline runner (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error starting pipeline runner',
    };
  }
}

export async function retryJobStage(jobId, stageId) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/jobs/${jobId}/retry-stage/${stageId}`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      return {
        success: false,
        status: response.status,
        error: (data && data.detail) || `Failed to retry stage (${response.status})`,
      };
    }

    return { success: true, status: response.status, data };
  } catch (error) {
    return {
      success: false,
      status: 0,
      error: error.message || 'Error retrying stage',
    };
  }
}




