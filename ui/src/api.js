const STORAGE_KEY = 'aws2.apiBase'

export const CAREER_POLICY_ID = 'career_cover_letter'
export const CAREER_ROLES = [
  ['W1', 'Evidence Intake'],
  ['W2', 'Company / Job Analysis'],
  ['W3', 'Strategy'],
  ['W4', 'Draft Writer'],
  ['W5', 'Fact Review'],
  ['W6', 'Reader Review'],
]

export function normalizeBaseUrl(value) {
  const trimmed = String(value || '').trim()
  if (!trimmed) return '/api'
  const normalized = trimmed.replace(/\/+$/, '')
  if (/^https?:\/\/(127\.0\.0\.1|localhost):8765$/i.test(normalized)) return `${normalized}/api`
  return normalized
}

export function defaultApiBase(runtime = globalThis) {
  return runtime && runtime.__TAURI_INTERNALS__ ? 'http://127.0.0.1:8765/api' : '/api'
}

export function loadApiBase() {
  return normalizeBaseUrl(localStorage.getItem(STORAGE_KEY) || defaultApiBase())
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
    probe: async () => {
      const health = await request('/health')
      const [agents, workflows, sessions] = await Promise.all([
        request('/agents'),
        request('/workflows'),
        request('/sessions'),
      ])
      return { health, agents, workflows, sessions }
    },
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
      files: (id) => request(`/sessions/${id}/files`),
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
      startWithFiles: (sessionId, userRequest, files = [], targetIds = []) => {
        const form = new FormData()
        form.append('session_id', sessionId)
        form.append('user_request', userRequest)
        targetIds.forEach((target) => form.append('target_ids', target))
        files.forEach((file) => form.append('files', file))
        return request('/runs/with-files', { method: 'POST', body: form })
      },
      get: (id) => request(`/runs/${id}`),
      history: (id) => request(`/runs/${id}/history`),
      resume: (id, payload) => request(`/runs/${id}/resume`, { method: 'POST', body: JSON.stringify(payload) }),
    },
    maintenance: {
      status: () => request('/maintenance/status'),
      backup: () => request('/maintenance/backups', { method: 'POST' }),
      cleanup: (apply = false) => request('/maintenance/cleanup', { method: 'POST', body: JSON.stringify({ apply }) }),
      importWorkspace: (file, conflictPolicy = 'fail') => {
        const form = new FormData()
        form.append('file', file)
        form.append('conflict_policy', conflictPolicy)
        return request('/maintenance/import-workspace', { method: 'POST', body: form })
      },
      validateBackup: (file) => {
        const form = new FormData()
        form.append('file', file)
        return request('/maintenance/validate-backup', { method: 'POST', body: form })
      },
    },
  }
}

export function validateWorkflowForm(form) {
  const errors = []
  const rows = (form.rows || []).filter((row) => row.agent_id)
  const ids = rows.map((row) => String(row.worker_id || '').trim()).filter(Boolean)
  if (ids.length !== new Set(ids).size) errors.push('Step/Worker Slot ID는 중복될 수 없습니다.')

  if (form.policy_id === CAREER_POLICY_ID) {
    if (form.mode !== 'hierarchical') errors.push('Career Cover Letter policy는 Hierarchical 구조가 필요합니다.')
    const allowed = new Set(CAREER_ROLES.map(([role]) => role))
    const roles = rows.map((row) => String(row.career_role || '').trim().toUpperCase())
    const invalid = roles.filter((role) => role && !allowed.has(role))
    const missing = CAREER_ROLES.map(([role]) => role).filter((role) => !roles.includes(role))
    const duplicates = roles.filter((role, index) => role && roles.indexOf(role) !== index)
    if (invalid.length) errors.push(`지원하지 않는 Career role: ${[...new Set(invalid)].join(', ')}`)
    if (missing.length) errors.push(`Career role 누락: ${missing.join(', ')}`)
    if (duplicates.length) errors.push(`Career role 중복: ${[...new Set(duplicates)].join(', ')}`)
  }
  return errors
}

export function workflowPayloadFromForm(form) {
  const errors = validateWorkflowForm(form)
  if (errors.length) throw new Error(errors.join(' '))

  const policyId = form.policy_id === CAREER_POLICY_ID ? CAREER_POLICY_ID : null
  const base = {
    id: form.id || undefined,
    name: form.name.trim(),
    mode: form.mode,
    include_original_prompt: form.include_original_prompt !== false,
    steps: [],
    hierarchy: null,
    policy_id: policyId,
    policy_config: {},
  }
  if (form.mode === 'linear') {
    base.steps = form.rows.filter((row) => row.agent_id).map((row, index) => ({
      step_id: row.worker_id || `step-${index + 1}`,
      agent_id: row.agent_id,
      additional_prompt: row.additional_prompt || '',
    }))
  } else {
    const workers = form.rows.filter((row) => row.agent_id).map((row, index) => ({
      worker_id: row.worker_id || `worker-${index + 1}`,
      agent_id: row.agent_id,
      additional_prompt: row.additional_prompt || '',
    }))
    base.hierarchy = {
      manager_agent_id: form.manager_agent_id,
      manager_planning_prompt: form.manager_planning_prompt || '',
      manager_synthesis_prompt: form.manager_synthesis_prompt || '',
      manager_routing_prompt: form.manager_routing_prompt || '',
      workers,
    }
    if (policyId === CAREER_POLICY_ID) {
      base.policy_config = {
        slot_roles: Object.fromEntries(
          form.rows
            .filter((row) => row.agent_id)
            .map((row, index) => [workers[index].worker_id, String(row.career_role || '').trim().toUpperCase()]),
        ),
      }
    }
  }
  return base
}