import { describe, expect, it } from 'vitest'
import { normalizeBaseUrl, workflowPayloadFromForm } from './api.js'

describe('normalizeBaseUrl', () => {
  it('uses local proxy by default', () => {
    expect(normalizeBaseUrl('')).toBe('/api')
  })

  it('removes trailing slashes', () => {
    expect(normalizeBaseUrl('http://127.0.0.1:8000///')).toBe('http://127.0.0.1:8000')
  })
})

describe('workflowPayloadFromForm', () => {
  it('preserves duplicate agent slots with distinct worker ids', () => {
    const payload = workflowPayloadFromForm({
      id: 'wf',
      name: 'Hierarchical',
      mode: 'hierarchical',
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

  it('builds ordered linear steps', () => {
    const payload = workflowPayloadFromForm({
      id: '',
      name: 'Linear',
      mode: 'linear',
      manager_agent_id: '',
      rows: [
        { worker_id: 'step-a', agent_id: 'a1', additional_prompt: 'first' },
        { worker_id: 'step-b', agent_id: 'a2', additional_prompt: 'second' },
      ],
    })
    expect(payload.hierarchy).toBeNull()
    expect(payload.steps.map((step) => step.step_id)).toEqual(['step-a', 'step-b'])
  })
})
