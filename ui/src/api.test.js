import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  CAREER_POLICY_ID,
  createApiClient,
  defaultApiBase,
  normalizeBaseUrl,
  validateWorkflowForm,
  workflowPayloadFromForm,
} from './api.js'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('API base', () => {
  it('uses local proxy by default', () => {
    expect(normalizeBaseUrl('')).toBe('/api')
    expect(defaultApiBase({})).toBe('/api')
  })

  it('uses the fixed loopback sidecar in Tauri', () => {
    expect(defaultApiBase({ __TAURI_INTERNALS__: {} })).toBe('http://127.0.0.1:8765/api')
  })

  it('repairs the known local backend root when /api is missing', () => {
    expect(normalizeBaseUrl('http://127.0.0.1:8765')).toBe('http://127.0.0.1:8765/api')
    expect(normalizeBaseUrl('http://localhost:8765///')).toBe('http://localhost:8765/api')
  })

  it('removes trailing slashes without rewriting unrelated hosts', () => {
    expect(normalizeBaseUrl('http://127.0.0.1:8000///')).toBe('http://127.0.0.1:8000')
  })

  it('marks a connection healthy only after mounted API resources respond', async () => {
    const ok = (body) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }))
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => ok({ status: 'ok' }))
      .mockImplementationOnce(() => ok([]))
      .mockImplementationOnce(() => Promise.resolve(new Response('Not Found', { status: 404 })))
      .mockImplementationOnce(() => ok([]))

    await expect(createApiClient('/api').probe()).rejects.toMatchObject({ status: 404 })
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.any(Object))
    expect(fetchMock).toHaveBeenCalledWith('/api/agents', expect.any(Object))
    expect(fetchMock).toHaveBeenCalledWith('/api/workflows', expect.any(Object))
  })
})

describe('workflowPayloadFromForm', () => {
  it('builds a Generic hierarchical workflow by default with arbitrary reusable Agents', () => {
    const payload = workflowPayloadFromForm({
      id: 'generic-h',
      name: 'Research Review',
      mode: 'hierarchical',
      policy_id: 'generic',
      manager_agent_id: 'coordinator',
      rows: [
        { worker_id: 'research-slot', agent_id: 'researcher', additional_prompt: '' },
        { worker_id: 'review-slot', agent_id: 'reviewer', additional_prompt: 'Review the evidence.' },
      ],
    })
    expect(payload.policy_id).toBeNull()
    expect(payload.policy_config).toEqual({})
    expect(payload.hierarchy.manager_agent_id).toBe('coordinator')
    expect(payload.hierarchy.workers.map((worker) => worker.worker_id)).toEqual(['research-slot', 'review-slot'])
  })

  it('preserves duplicate agent slots with distinct worker ids', () => {
    const payload = workflowPayloadFromForm({
      id: 'wf',
      name: 'Hierarchical',
      mode: 'hierarchical',
      policy_id: 'generic',
      manager_agent_id: 'manager',
      rows: [
        { worker_id: 'slot-a', agent_id: 'worker-agent', additional_prompt: '' },
        { worker_id: 'slot-b', agent_id: 'worker-agent', additional_prompt: 'second role' },
      ],
    })
    expect(payload.hierarchy.workers).toHaveLength(2)
    expect(payload.hierarchy.workers[0].worker_id).not.toBe(payload.hierarchy.workers[1].worker_id)
    expect(payload.hierarchy.workers[0].agent_id).toBe(payload.hierarchy.workers[1].agent_id)
  })

  it('builds ordered Generic linear steps', () => {
    const payload = workflowPayloadFromForm({
      id: '',
      name: 'Linear',
      mode: 'linear',
      policy_id: 'generic',
      manager_agent_id: '',
      rows: [
        { worker_id: 'step-a', agent_id: 'a1', additional_prompt: 'first' },
        { worker_id: 'step-b', agent_id: 'a2', additional_prompt: 'second' },
      ],
    })
    expect(payload.policy_id).toBeNull()
    expect(payload.hierarchy).toBeNull()
    expect(payload.steps.map((step) => step.step_id)).toEqual(['step-a', 'step-b'])
  })

  it('maps Career roles explicitly by WorkerSlot instead of Agent name', () => {
    const rows = Array.from({ length: 6 }, (_, index) => ({
      worker_id: `slot-${index + 1}`,
      agent_id: `reusable-agent-${index + 1}`,
      additional_prompt: '',
      career_role: `W${index + 1}`,
    }))
    const payload = workflowPayloadFromForm({
      id: 'career',
      name: 'Career Cover Letter',
      mode: 'hierarchical',
      policy_id: CAREER_POLICY_ID,
      manager_agent_id: 'editor',
      rows,
    })
    expect(payload.policy_id).toBe(CAREER_POLICY_ID)
    expect(payload.policy_config.slot_roles).toEqual({
      'slot-1': 'W1',
      'slot-2': 'W2',
      'slot-3': 'W3',
      'slot-4': 'W4',
      'slot-5': 'W5',
      'slot-6': 'W6',
    })
  })

  it('pre-validates missing and duplicate Career roles before save', () => {
    const form = {
      name: 'Career',
      mode: 'hierarchical',
      policy_id: CAREER_POLICY_ID,
      manager_agent_id: 'manager',
      rows: [
        { worker_id: 'a', agent_id: 'agent-a', career_role: 'W1' },
        { worker_id: 'b', agent_id: 'agent-b', career_role: 'W1' },
      ],
    }
    const errors = validateWorkflowForm(form)
    expect(errors.join(' ')).toContain('Career role 누락')
    expect(errors.join(' ')).toContain('Career role 중복')
    expect(() => workflowPayloadFromForm(form)).toThrow('Career role')
  })

  it('rejects Career policy on a Linear workflow', () => {
    expect(validateWorkflowForm({
      name: 'Career',
      mode: 'linear',
      policy_id: CAREER_POLICY_ID,
      rows: [],
    }).join(' ')).toContain('Hierarchical')
  })
})