const STORAGE_KEY = 'aws2.apiBase'

export function normalizeBaseUrl(value) {
  const trimmed = String(value || '').trim()
  if (!trimmed) return '/api'
  return trimmed.replace(/\/+$/, '')
}

export function loadApiBase() {
  return normalizeBaseUrl(localStorage.getItem(STORAGE_KEY) || '/api')
}

export function saveApiBase(value) {
  const normalized = normalizeBaseUrl(value)
  localStorage.setItem(STORAGE_KEY, normalized)
  return normalized
}

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function parseResponse(response) {
  if (response.status === 204) return null
  const type = response.headers.get('content-type') || ''
  const body = type.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail = body && typeof body === 'object' ? body.detail : body
    throw new ApiError(detail || `HTTP ${response.status}`, response.status, detail)
  }
  return body
}

export function createApiClient(baseUrl = loadApiBase()) {
  const base = normalizeBaseUrl(baseUrl)
  const request = async (path, options = {}) => {
    const headers = new Headers(options.headers || {})
    if (options.body && !(options.body instanceof FormData) && !headers.has('content-type')) {
      headers.set('content-type', 'application/json')
    }
    const response = await fetch(`${base}${path}`, { ...options, headers })
    return parseResponse(response)
  }
  return {
    health: () => request('/health'),
    agents: {
      list: () => request('/agents'),
      get: (id) => request(`/agents/${id}`),
      create: (payload) => request('/agents', { method: 'POST', body: JSON.stringify(payload) }),
      update: async (id, payload) => {
        const existing = await request(`/agents/${id}`)
        const merged = {
          ...payload,
          source_ids: existing.source_ids || [],
          notion_enabled: !!existing.notion_enabled,
          notion_sources: existing.notion_sources || [],
        }
        return request(`/agents/${id}`, { method: 'PUT', body: JSON.stringify(merged) })
      },
      remove: (id) => request(`/agents/${id}`, { method: 'DELETE' }),
    },
    workflows: {
      list: () => request('/workflows'),
      get: (id) => request(`/workflows/${id}`),
      create: (payload) => request('/workflows', { method: 'POST', body: JSON.stringify(payload) }),
      update: async (id, payload) => {
        const existing = await request(`/workflows/${id}`)
        const merged = { ...payload }
        if (payload.mode === 'hierarchical' && existing.mode === 'hierarchical' && existing.hierarchy) {
          merged.hierarchy = {
            ...payload.hierarchy,
            manager_planning_prompt: existing.hierarchy.manager_planning_prompt || payload.hierarchy?.manager_planning_prompt || '',
            manager_synthesis_prompt: existing.hierarchy.manager_synthesis_prompt || payload.hierarchy?.manager_synthesis_prompt || '',
            manager_routing_prompt: existing.hierarchy.manager_routing_prompt || payload.hierarchy?.manager_routing_prompt || '',
          }
        }
        return request(`/workflows/${id}`, { method: 'PUT', body: JSON.stringify(merged) })
      },
      remove: (id) => request(`/workflows/${id}`, { method: 'DELETE' }),
    },
    sessions: {
      list: () => request('/sessions'),
      create: (payload) => request('/sessions', { method: 'POST', body: JSON.stringify(payload) }),
      messages: (id) => request(`/sessions/${id}/messages`),
      runs: (id) => request(`/sessions/${id}/runs`),
      artifacts: (id) => request(`/sessions/${id}/artifacts`),
      revisions: (id) => request(`/sessions/${id}/revisions`),
      followUp: (id, previousRunId, content, files = []) => {
        const form = new FormData()
        form.append('previous_run_id', previousRunId)
        form.append('content', content)
        files.forEach((file) => form.append('files', file))
        return request(`/sessions/${id}/messages`, { method: 'POST', body: form })
      },
    },
    runs: {
      start: (payload) => request('/runs', { method: 'POST', body: JSON.stringify(payload) }),
      get: (id) => request(`/runs/${id}`),
      history: (id) => request(`/runs/${id}/history`),
      resume: (id, payload) => request(`/runs/${id}/resume`, { method: 'POST', body: JSON.stringify(payload) }),
    },
  }
}

export function workflowPayloadFromForm(form) {
  const base = {
    id: form.id || undefined,
    name: form.name.trim(),
    mode: form.mode,
    include_original_prompt: form.include_original_prompt !== false,
    steps: [],
    hierarchy: null,
  }
  if (form.mode === 'linear') {
    base.steps = form.rows.filter((row) => row.agent_id).map((row, index) => ({
      step_id: row.worker_id || `step-${index + 1}`,
      agent_id: row.agent_id,
      additional_prompt: row.additional_prompt || '',
    }))
  } else {
    base.hierarchy = {
      manager_agent_id: form.manager_agent_id,
      manager_planning_prompt: form.manager_planning_prompt || '',
      manager_synthesis_prompt: form.manager_synthesis_prompt || '',
      manager_routing_prompt: form.manager_routing_prompt || '',
      workers: form.rows.filter((row) => row.agent_id).map((row, index) => ({
        worker_id: row.worker_id || `worker-${index + 1}`,
        agent_id: row.agent_id,
        additional_prompt: row.additional_prompt || '',
      })),
    }
  }
  return base
}
