import { useEffect, useMemo, useState } from 'react'
import { createApiClient, loadApiBase, saveApiBase, workflowPayloadFromForm } from './api.js'

const navItems = [
  ['run', 'Run Studio'],
  ['agents', 'Agents'],
  ['workflows', 'Workflows'],
  ['history', 'History'],
  ['settings', 'Settings'],
]

const emptyAgent = () => ({ id: '', name: '', model: 'gpt-5.6-luna', system_prompt: '', rag_enabled: false, rag_top_k: 5 })
const emptyWorkflow = () => ({ id: '', name: '', mode: 'hierarchical', manager_agent_id: '', rows: [{ worker_id: 'worker-1', agent_id: '', additional_prompt: '' }] })

function Button({ children, tone = 'primary', ...props }) {
  return <button className={`button ${tone}`} {...props}>{children}</button>
}

function Field({ label, children, hint }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

function StatusPill({ value }) {
  const key = String(value || 'UNKNOWN').toLowerCase()
  return <span className={`status ${key}`}>{value || 'UNKNOWN'}</span>
}

function Empty({ title, body }) {
  return <div className="empty"><strong>{title}</strong><p>{body}</p></div>
}

function Card({ title, meta, children, actions }) {
  return <section className="card"><div className="card-head"><div><h3>{title}</h3>{meta && <p>{meta}</p>}</div>{actions}</div>{children}</section>
}

function formatTime(value) {
  if (!value) return '—'
  try { return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) } catch { return value }
}

function latestRevision(revisions) {
  return [...revisions].sort((a, b) => (b.version || b.revision || 0) - (a.version || a.revision || 0))[0]
}

function AgentsPage({ api, agents, refresh, notify }) {
  const [form, setForm] = useState(emptyAgent())
  const [editing, setEditing] = useState(null)
  const save = async (event) => {
    event.preventDefault()
    const payload = { ...form, id: form.id || undefined, name: form.name.trim(), model: form.model.trim(), system_prompt: form.system_prompt, source_ids: [], notion_enabled: false, notion_sources: [] }
    try {
      if (editing) await api.agents.update(editing, payload)
      else await api.agents.create(payload)
      notify(editing ? 'Agent가 수정되었습니다.' : 'Agent가 생성되었습니다.')
      setEditing(null); setForm(emptyAgent()); await refresh()
    } catch (error) { notify(error.message, 'error') }
  }
  const edit = (agent) => {
    setEditing(agent.id)
    setForm({ id: agent.id, name: agent.name, model: agent.model, system_prompt: agent.system_prompt || '', rag_enabled: !!agent.rag_enabled, rag_top_k: agent.rag_top_k || 5 })
  }
  const remove = async (id) => {
    if (!confirm('이 Agent를 삭제할까요? 연결된 Workflow가 있으면 API가 삭제를 거부할 수 있습니다.')) return
    try { await api.agents.remove(id); notify('Agent가 삭제되었습니다.'); await refresh() } catch (error) { notify(error.message, 'error') }
  }
  return <div className="two-column">
    <div><div className="section-title"><div><span className="eyebrow">CONFIGURATION</span><h2>Agents</h2><p>모델과 역할 지침을 Form 방식으로 관리합니다.</p></div></div>
      <div className="stack">{agents.length ? agents.map((agent) => <Card key={agent.id} title={agent.name} meta={`${agent.model} · ${agent.id}`} actions={<div className="row"><Button tone="ghost" onClick={() => edit(agent)}>수정</Button><Button tone="danger" onClick={() => remove(agent.id)}>삭제</Button></div>}><p className="clamp">{agent.system_prompt || 'System prompt 없음'}</p></Card>) : <Empty title="Agent가 없습니다" body="오른쪽 폼에서 첫 Agent를 생성하세요." />}</div>
    </div>
    <form className="panel sticky" onSubmit={save}><div className="panel-title"><h3>{editing ? 'Agent 수정' : '새 Agent'}</h3>{editing && <Button type="button" tone="ghost" onClick={() => { setEditing(null); setForm(emptyAgent()) }}>취소</Button>}</div>
      <Field label="ID" hint="비워두면 자동 생성됩니다."><input disabled={!!editing} value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} placeholder="agent-w1" /></Field>
      <Field label="이름"><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Evidence Manager" /></Field>
      <Field label="모델"><input required value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></Field>
      <Field label="System prompt"><textarea rows="9" value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} placeholder="이 Agent의 역할과 제약을 입력하세요." /></Field>
      <div className="inline-fields"><label className="check"><input type="checkbox" checked={form.rag_enabled} onChange={(e) => setForm({ ...form, rag_enabled: e.target.checked })} />RAG 사용</label><Field label="Top K"><input type="number" min="1" max="20" value={form.rag_top_k} onChange={(e) => setForm({ ...form, rag_top_k: Number(e.target.value) })} /></Field></div>
      <Button type="submit">{editing ? '변경 저장' : 'Agent 생성'}</Button>
    </form>
  </div>
}

function WorkflowsPage({ api, agents, workflows, refresh, notify }) {
  const [form, setForm] = useState(emptyWorkflow())
  const [editing, setEditing] = useState(null)
  const addRow = () => setForm({ ...form, rows: [...form.rows, { worker_id: `worker-${form.rows.length + 1}`, agent_id: '', additional_prompt: '' }] })
  const patchRow = (index, patch) => setForm({ ...form, rows: form.rows.map((row, i) => i === index ? { ...row, ...patch } : row) })
  const save = async (event) => {
    event.preventDefault()
    try {
      const payload = workflowPayloadFromForm(form)
      if (editing) await api.workflows.update(editing, payload)
      else await api.workflows.create(payload)
      notify(editing ? 'Workflow가 수정되었습니다.' : 'Workflow가 생성되었습니다.')
      setEditing(null); setForm(emptyWorkflow()); await refresh()
    } catch (error) { notify(error.message, 'error') }
  }
  const edit = (wf) => {
    const hierarchical = wf.mode === 'hierarchical'
    setEditing(wf.id)
    setForm({
      id: wf.id,
      name: wf.name,
      mode: wf.mode,
      manager_agent_id: hierarchical ? wf.hierarchy?.manager_agent_id || '' : '',
      rows: hierarchical ? (wf.hierarchy?.workers || []) : (wf.steps || []).map((step) => ({ worker_id: step.step_id, agent_id: step.agent_id, additional_prompt: step.additional_prompt || '' })),
    })
  }
  const remove = async (id) => {
    if (!confirm('이 Workflow를 삭제할까요?')) return
    try { await api.workflows.remove(id); notify('Workflow가 삭제되었습니다.'); await refresh() } catch (error) { notify(error.message, 'error') }
  }
  return <div className="two-column wide-form">
    <div><div className="section-title"><div><span className="eyebrow">ORCHESTRATION</span><h2>Workflows</h2><p>Visual node editor 대신 명확한 Form/List 방식으로 구성합니다.</p></div></div>
      <div className="stack">{workflows.length ? workflows.map((wf) => <Card key={wf.id} title={wf.name} meta={`${wf.mode} · ${wf.id}`} actions={<div className="row"><Button tone="ghost" onClick={() => edit(wf)}>수정</Button><Button tone="danger" onClick={() => remove(wf.id)}>삭제</Button></div>}><div className="chips"><span>{wf.mode === 'hierarchical' ? `Workers ${wf.hierarchy?.workers?.length || 0}` : `Steps ${wf.steps?.length || 0}`}</span>{wf.hierarchy?.manager_agent_id && <span>Manager {wf.hierarchy.manager_agent_id}</span>}</div></Card>) : <Empty title="Workflow가 없습니다" body="Agent를 만든 뒤 새 Workflow를 구성하세요." />}</div>
    </div>
    <form className="panel sticky" onSubmit={save}><div className="panel-title"><h3>{editing ? 'Workflow 수정' : '새 Workflow'}</h3>{editing && <Button type="button" tone="ghost" onClick={() => { setEditing(null); setForm(emptyWorkflow()) }}>취소</Button>}</div>
      <Field label="ID"><input disabled={!!editing} value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} placeholder="career-workflow" /></Field>
      <Field label="이름"><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
      <Field label="구조"><select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}><option value="hierarchical">Hierarchical</option><option value="linear">Linear</option></select></Field>
      {form.mode === 'hierarchical' && <Field label="Manager Agent"><select required value={form.manager_agent_id} onChange={(e) => setForm({ ...form, manager_agent_id: e.target.value })}><option value="">선택</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></Field>}
      <div className="worker-header"><strong>{form.mode === 'linear' ? 'Steps' : 'Workers'}</strong><Button type="button" tone="ghost" onClick={addRow}>+ 추가</Button></div>
      <div className="workers">{form.rows.map((row, index) => <div className="worker" key={`${index}-${row.worker_id}`}><input aria-label="slot id" value={row.worker_id} onChange={(e) => patchRow(index, { worker_id: e.target.value })} placeholder={form.mode === 'linear' ? 'step-1' : 'worker-1'} /><select required value={row.agent_id} onChange={(e) => patchRow(index, { agent_id: e.target.value })}><option value="">Agent 선택</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select><textarea rows="2" value={row.additional_prompt} onChange={(e) => patchRow(index, { additional_prompt: e.target.value })} placeholder="추가 지침 (선택)" /><button className="icon-button" type="button" aria-label="remove worker" onClick={() => setForm({ ...form, rows: form.rows.filter((_, i) => i !== index) })}>×</button></div>)}</div>
      <Button type="submit">{editing ? '변경 저장' : 'Workflow 생성'}</Button>
    </form>
  </div>
}

function RunStudio({ api, workflows, sessions, onRefreshSessions, notify }) {
  const [sessionId, setSessionId] = useState(sessions[0]?.id || '')
  const [workflowId, setWorkflowId] = useState(workflows[0]?.id || '')
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [initialFiles, setInitialFiles] = useState([])
  const [run, setRun] = useState(null)
  const [history, setHistory] = useState([])
  const [sessionData, setSessionData] = useState({ runs: [], messages: [], revisions: [], artifacts: [], files: [] })
  const [answer, setAnswer] = useState('')
  const [followUp, setFollowUp] = useState('')
  const [followFiles, setFollowFiles] = useState([])
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (!sessionId && sessions[0]) setSessionId(sessions[0].id) }, [sessions, sessionId])
  const loadRun = async (id) => {
    try { const [detail, checkpoints] = await Promise.all([api.runs.get(id), api.runs.history(id)]); setRun(detail); setHistory(checkpoints) } catch (error) { notify(error.message, 'error') }
  }
  const loadSession = async (id = sessionId) => {
    if (!id) return
    try {
      const [runs, messages, revisions, artifacts, files] = await Promise.all([api.sessions.runs(id), api.sessions.messages(id), api.sessions.revisions(id), api.sessions.artifacts(id), api.sessions.files(id)])
      setSessionData({ runs, messages, revisions, artifacts, files })
      const latest = [...runs].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0]
      if (latest) await loadRun(latest.id)
    } catch (error) { notify(error.message, 'error') }
  }
  useEffect(() => { loadSession() }, [sessionId])
  const createSession = async () => {
    if (!workflowId) return notify('Workflow를 먼저 선택하세요.', 'error')
    try { const created = await api.sessions.create({ workflow_id: workflowId, title: title || 'Untitled Session' }); await onRefreshSessions(); setSessionId(created.id); notify('Session이 생성되었습니다.') } catch (error) { notify(error.message, 'error') }
  }
  const start = async () => {
    if (!sessionId || !prompt.trim()) return notify('Session과 요청 내용을 입력하세요.', 'error')
    setBusy(true)
    try {
      const outcome = initialFiles.length
        ? await api.runs.startWithFiles(sessionId, prompt.trim(), initialFiles)
        : await api.runs.start({ session_id: sessionId, user_request: prompt.trim() })
      notify(`Run ${outcome.status}`)
      setInitialFiles([])
      await loadSession(sessionId)
    } catch (error) { notify(error.message, 'error') } finally { setBusy(false) }
  }
  const resume = async (mode) => {
    const id = run?.run?.id
    if (!id) return
    setBusy(true)
    try { await api.runs.resume(id, mode === 'user' ? { mode, answer } : { mode }); notify('Run을 재개했습니다.'); setAnswer(''); await loadSession(sessionId) } catch (error) { notify(error.message, 'error') } finally { setBusy(false) }
  }
  const submitFollowUp = async () => {
    const current = run?.run
    if (!current || current.status !== 'COMPLETED' || !followUp.trim()) return
    setBusy(true)
    try { await api.sessions.followUp(sessionId, current.id, followUp.trim(), followFiles); notify('Continuation Run이 완료되었습니다.'); setFollowUp(''); setFollowFiles([]); await loadSession(sessionId) } catch (error) { notify(error.message, 'error') } finally { setBusy(false) }
  }
  const state = run?.state || {}
  const status = run?.run?.status
  const revision = latestRevision(sessionData.revisions)
  return <div className="studio-grid">
    <div className="stack">
      <section className="hero"><span className="eyebrow">LOCAL-FIRST ORCHESTRATION</span><h2>Run Studio</h2><p>Workflow Session을 만들고 실행·중단·재개·후속수정을 한 화면에서 관리합니다.</p></section>
      <Card title="1. Session 선택 또는 생성"><div className="form-grid"><Field label="기존 Session"><select value={sessionId} onChange={(e) => setSessionId(e.target.value)}><option value="">선택</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.title || session.id}</option>)}</select></Field><Field label="새 Session Workflow"><select value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}><option value="">선택</option>{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</select></Field><Field label="Session 이름"><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="LG엔솔 자기소개서" /></Field><div className="field button-field"><span>&nbsp;</span><Button onClick={createSession}>새 Session</Button></div></div></Card>
      <Card title="2. Initial Run"><Field label="사용자 요청"><textarea rows="6" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="검증된 경험을 바탕으로 자기소개서를 작성해줘." /></Field><Field label="실행 파일" hint="LLM 실행 전에 로컬 저장소에 먼저 영구 기록되며, Target 미지정 시 전체 Workflow에서 참조할 수 있습니다."><input type="file" multiple onChange={(e) => setInitialFiles([...e.target.files])} /></Field><small>{initialFiles.length ? `${initialFiles.length}개 파일 선택됨` : '파일 첨부는 선택입니다.'}</small><Button disabled={busy || !sessionId} onClick={start}>{busy ? '실행 중…' : 'Run 시작'}</Button></Card>
      {run && <Card title="3. Active / Latest Run" meta={`${run.run.id} · ${formatTime(run.run.updated_at)}`} actions={<StatusPill value={status} />}>
        <div className="metric-row"><div><span>Current stage</span><strong>{state.current_stage || '—'}</strong></div><div><span>Thread</span><strong>{run.thread_id}</strong></div><div><span>Checkpoints</span><strong>{history.length}</strong></div><div><span>Session files</span><strong>{sessionData.files.length}</strong></div></div>
        {status === 'WAITING_FOR_USER' && <div className="action-box warning"><h4>Agent가 사용자 입력을 기다립니다</h4><p>{state.interrupt_prompt || state.question || '응답을 입력한 뒤 Resume 하세요.'}</p><textarea rows="3" value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="답변" /><Button disabled={busy || !answer.trim()} onClick={() => resume('user')}>같은 Run에서 Resume</Button></div>}
        {status === 'PAUSED' && <div className="action-box danger-box"><h4>오류로 일시정지됨</h4><p>{state.error_message || '문제를 확인한 뒤 수동으로 재개할 수 있습니다.'}</p><Button disabled={busy} onClick={() => resume('error')}>Manual Resume</Button></div>}
        {status === 'COMPLETED' && <div className="action-box"><h4>Manager 결과 후 Follow-up</h4>{revision && <div className="result"><span>Revision v{revision.version || revision.revision}</span><p>{revision.final_output || revision.output || 'Revision output saved.'}</p></div>}<textarea rows="4" value={followUp} onChange={(e) => setFollowUp(e.target.value)} placeholder="예: 3번 문항을 첨부 실험결과 기준으로 수정해줘." /><input type="file" multiple onChange={(e) => setFollowFiles([...e.target.files])} /><small>{followFiles.length ? `${followFiles.length}개 파일 선택됨 · 이번 Follow-up에만 사용` : '첨부파일은 기본 Turn-scoped이며 영구 RAG로 승격되지 않습니다.'}</small><Button disabled={busy || !followUp.trim()} onClick={submitFollowUp}>Continuation Run 생성</Button></div>}
      </Card>}
    </div>
    <aside className="timeline panel"><div className="panel-title"><h3>Session timeline</h3><Button tone="ghost" onClick={() => loadSession()}>새로고침</Button></div>{sessionData.runs.length ? [...sessionData.runs].reverse().map((item) => <button className={`timeline-item ${run?.run?.id === item.id ? 'selected' : ''}`} key={item.id} onClick={() => loadRun(item.id)}><div><strong>{item.kind || 'Run'}</strong><small>{item.id}</small></div><StatusPill value={item.status} /></button>) : <Empty title="Run 이력 없음" body="Initial Run을 시작하면 여기에 기록됩니다." />}</aside>
  </div>
}

function HistoryPage({ api, sessions, notify }) {
  const [sessionId, setSessionId] = useState(sessions[0]?.id || '')
  const [data, setData] = useState({ runs: [], messages: [], revisions: [], artifacts: [], files: [] })
  const load = async () => {
    if (!sessionId) return
    try {
      const [runs, messages, revisions, artifacts, files] = await Promise.all([api.sessions.runs(sessionId), api.sessions.messages(sessionId), api.sessions.revisions(sessionId), api.sessions.artifacts(sessionId), api.sessions.files(sessionId)])
      setData({ runs, messages, revisions, artifacts, files })
    } catch (error) { notify(error.message, 'error') }
  }
  useEffect(() => { load() }, [sessionId])
  return <div><div className="section-title"><div><span className="eyebrow">DURABLE RECORD</span><h2>History</h2><p>Session별 Run, Message, Artifact, Revision, 실행 파일을 한곳에서 확인합니다.</p></div><select className="compact-select" value={sessionId} onChange={(e) => setSessionId(e.target.value)}><option value="">Session 선택</option>{sessions.map((session) => <option key={session.id} value={session.id}>{session.title || session.id}</option>)}</select></div>
    {!sessionId ? <Empty title="Session을 선택하세요" body="이력은 Workflow Session 단위로 보존됩니다." /> : <div className="history-grid"><Card title={`Runs · ${data.runs.length}`}>{data.runs.map((run) => <div className="record" key={run.id}><div><strong>{run.kind}</strong><small>{run.id}</small></div><StatusPill value={run.status} /></div>)}</Card><Card title={`Revisions · ${data.revisions.length}`}>{data.revisions.map((revision) => <div className="record block" key={revision.id}><strong>Revision v{revision.version || revision.revision}</strong><p>{revision.final_output || 'Output persisted'}</p></div>)}</Card><Card title={`Messages · ${data.messages.length}`}>{data.messages.map((message) => <div className="record block" key={message.id}><strong>{message.role}</strong><p>{message.content}</p><small>Attachments {message.attachment_ids?.length || 0}</small></div>)}</Card><Card title={`Execution files · ${data.files.length}`}>{data.files.map((file) => <div className="record block" key={file.id}><strong>{file.filename}</strong><small>{file.run_id}</small><p>{file.target_ids?.length ? `Targets: ${file.target_ids.join(', ')}` : 'All workflow targets'}</p></div>)}</Card><Card title={`Artifacts · ${data.artifacts.length}`}>{data.artifacts.map((artifact) => <div className="record block" key={artifact.id}><strong>{artifact.kind}</strong><small>{artifact.producer || artifact.worker_id || artifact.worker_name || 'manager'}</small><p>{artifact.body || artifact.output}</p></div>)}</Card></div>}
  </div>
}

function SettingsPage({ api, apiBase, onSave, health, notify, onChanged }) {
  const [value, setValue] = useState(apiBase)
  const [status, setStatus] = useState(null)
  const [workspaceFile, setWorkspaceFile] = useState(null)
  const [backupFile, setBackupFile] = useState(null)
  const [conflictPolicy, setConflictPolicy] = useState('fail')
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)

  const refreshStatus = async () => {
    try { setStatus(await api.maintenance.status()) } catch (error) { notify(error.message, 'error') }
  }
  useEffect(() => { if (health === 'ok') refreshStatus() }, [health, api])
  const execute = async (work, success, changed = false) => {
    setBusy(true)
    try {
      const result = await work()
      setReport(result)
      notify(success)
      await refreshStatus()
      if (changed && onChanged) await onChanged()
    } catch (error) { notify(error.message, 'error') } finally { setBusy(false) }
  }
  const applyCleanup = () => {
    if (!confirm('DB에서 참조되지 않는 로컬 파일만 삭제합니다. 계속할까요?')) return
    execute(() => api.maintenance.cleanup(true), '미참조 파일 정리를 완료했습니다.')
  }
  return <div className="settings-wrap"><div className="section-title"><div><span className="eyebrow">LOCAL SETTINGS</span><h2>Settings</h2><p>연결, legacy migration, backup, cleanup을 관리합니다. Secret은 브라우저에 저장하지 않습니다.</p></div></div>
    <Card title="Backend connection" actions={<StatusPill value={health === 'ok' ? 'CONNECTED' : 'DISCONNECTED'} />}><Field label="API Base URL" hint="브라우저 개발은 /api, Tauri Desktop은 기본적으로 127.0.0.1:8765/api를 사용합니다."><input value={value} onChange={(e) => setValue(e.target.value)} placeholder="/api" /></Field><Button onClick={() => onSave(value)}>저장 및 재연결</Button>{status && <div className="metric-row"><div><span>Version</span><strong>{status.version}</strong></div><div><span>Schema</span><strong>{status.schema_version}</strong></div><div><span>Active runs</span><strong>{status.active_runs?.length || 0}</strong></div></div>}</Card>
    <Card title="Legacy Workspace import" meta="agent_workspace.zip · schema v1–v4"><Field label="Workspace ZIP" hint="Agent 설정, Linear/Hierarchical Workflow, RAG 원본, Notion source reference를 import합니다. 실행 이력과 secret은 legacy ZIP 대상이 아닙니다."><input type="file" accept=".zip,application/zip" onChange={(e) => setWorkspaceFile(e.target.files?.[0] || null)} /></Field><Field label="충돌 정책"><select value={conflictPolicy} onChange={(e) => setConflictPolicy(e.target.value)}><option value="fail">Fail — 기존 ID가 있으면 중단</option><option value="skip">Skip — 기존 항목 유지</option></select></Field><Button disabled={busy || !workspaceFile} onClick={() => execute(() => api.maintenance.importWorkspace(workspaceFile, conflictPolicy), 'Legacy Workspace import가 완료되었습니다.', true)}>Workspace Import</Button></Card>
    <Card title="Backup & recovery" meta="domain.sqlite + graph.sqlite + local files"><div className="row"><Button disabled={busy} onClick={() => execute(() => api.maintenance.backup(), '검증된 로컬 Backup을 생성했습니다.')}>Backup 생성</Button><Button tone="ghost" disabled={busy || !backupFile} onClick={() => execute(() => api.maintenance.validateBackup(backupFile), 'Backup 검증을 완료했습니다.')}>Backup 검증</Button></div><Field label="검증할 Backup ZIP" hint="Restore는 실행 중 데이터 변경을 막기 위해 offline CLI에서만 허용합니다."><input type="file" accept=".zip,application/zip" onChange={(e) => setBackupFile(e.target.files?.[0] || null)} /></Field><p><code>python scripts/restore_backup.py &lt;backup.zip&gt; --overwrite</code></p></Card>
    <Card title="Local file cleanup" meta="Dry-run first"><p>Source, Message attachment, Run execution file로 참조되는 데이터는 삭제하지 않습니다. DB에서 참조되지 않는 파일만 후보가 됩니다.</p><div className="row"><Button tone="ghost" disabled={busy} onClick={() => execute(() => api.maintenance.cleanup(false), 'Cleanup 후보를 확인했습니다.')}>Dry-run</Button><Button tone="danger" disabled={busy} onClick={applyCleanup}>미참조 파일 삭제</Button></div></Card>
    <Card title="Security boundary"><p>OpenAI, Notion, Discord credential은 backend 환경변수에서만 읽습니다. Backup·Workspace import·SQLite·로그에는 secret을 저장하지 않습니다.</p></Card>
    {report && <Card title="Latest maintenance result"><pre className="result">{JSON.stringify(report, null, 2)}</pre></Card>}
  </div>
}

export default function App() {
  const [page, setPage] = useState('run')
  const [apiBase, setApiBase] = useState(loadApiBase())
  const api = useMemo(() => createApiClient(apiBase), [apiBase])
  const [health, setHealth] = useState('checking')
  const [agents, setAgents] = useState([])
  const [workflows, setWorkflows] = useState([])
  const [sessions, setSessions] = useState([])
  const [toast, setToast] = useState(null)
  const notify = (message, tone = 'success') => { setToast({ message, tone }); window.setTimeout(() => setToast(null), 3500) }
  const refreshAgents = async () => setAgents(await api.agents.list())
  const refreshWorkflows = async () => setWorkflows(await api.workflows.list())
  const refreshSessions = async () => setSessions(await api.sessions.list())
  const hydrate = async () => {
    try { await api.health(); setHealth('ok'); const [agentItems, workflowItems, sessionItems] = await Promise.all([api.agents.list(), api.workflows.list(), api.sessions.list()]); setAgents(agentItems); setWorkflows(workflowItems); setSessions(sessionItems) } catch { setHealth('down') }
  }
  useEffect(() => { hydrate() }, [api])
  const saveBase = (value) => { const saved = saveApiBase(value); setApiBase(saved); notify('API 연결 설정을 저장했습니다.') }
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><div className="brand-mark">AW</div><div><strong>Agent Workflow</strong><span>Studio 2.0</span></div></div><nav>{navItems.map(([id, label]) => <button className={page === id ? 'active' : ''} key={id} onClick={() => setPage(id)}>{label}</button>)}</nav><div className="backend-state"><span className={`dot ${health}`}></span><div><strong>Local Backend</strong><small>{health === 'ok' ? 'Connected' : health === 'checking' ? 'Checking…' : 'Disconnected'}</small></div></div></aside>
    <main className="content"><header className="topbar"><div><strong>Agent Workflow Studio</strong><span>Local-first · Durable · Single active run</span></div><Button tone="ghost" onClick={hydrate}>Sync</Button></header><div className="page">
      {page === 'run' && <RunStudio api={api} workflows={workflows} sessions={sessions} onRefreshSessions={refreshSessions} notify={notify} />}
      {page === 'agents' && <AgentsPage api={api} agents={agents} refresh={refreshAgents} notify={notify} />}
      {page === 'workflows' && <WorkflowsPage api={api} agents={agents} workflows={workflows} refresh={refreshWorkflows} notify={notify} />}
      {page === 'history' && <HistoryPage api={api} sessions={sessions} notify={notify} />}
      {page === 'settings' && <SettingsPage api={api} apiBase={apiBase} onSave={saveBase} health={health} notify={notify} onChanged={hydrate} />}
    </div></main>
    {toast && <div className={`toast ${toast.tone}`}>{toast.message}</div>}
  </div>
}
