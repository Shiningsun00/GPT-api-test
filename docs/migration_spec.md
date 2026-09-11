# Agent Workflow Studio 2.0 — STEP 0 Migration Specification

> 상태: **STEP 0 baseline specification**  
> 기준 저장소: `Shiningsun00/GPT-api-test`  
> 기준 브랜치/커밋: `main` / `04b4e575aeb4a1282a56cf521ddb0ec36c8ee6fb`  
> 기준 애플리케이션: `app.py`  
> 현재 Workspace schema: **v4**

---

## 1. STEP 0 목표와 범위

이 문서는 현재 Streamlit 기반 Agent Workflow Studio의 기능, 런타임 상태, 데이터 구조와 외부 연동을 동결된 baseline으로 정리하고, 2.0 구조로 이동할 때 기능 손실이 발생하지 않도록 Migration 기준을 정의한다.

STEP 0에서는 신규 실행 기능을 구현하지 않는다. `app.py`는 레퍼런스 구현으로 유지하며, 이후 단계에서 Core → Persistence → LangGraph → FastAPI → UI 순서로 분리한다.

### 현재 저장소 구성

```text
GPT-api-test/
├─ .devcontainer/
│  └─ devcontainer.json
├─ README.md
├─ agent_workspace.zip
├─ app.py
└─ requirements.txt
```

현재 `requirements.txt`의 핵심 의존성은 Streamlit, OpenAI SDK, NumPy 및 PDF/DOCX/XLSX/PPTX 파서다. `.devcontainer` 역시 `streamlit run app.py`를 직접 실행하도록 구성되어 있어 현재 프로젝트는 UI와 Engine이 사실상 하나의 프로세스로 결합되어 있다.

---

# 2. 현재 기능 인벤토리

아래 기능은 2.0 Migration에서 누락 여부를 추적해야 하는 baseline이다.

## 2.1 Agent 관리

| 기능 | 현재 상태 | 2.0 처리 |
|---|---|---|
| Agent 생성 | 구현 | 유지 |
| Agent 수정 | 구현 | 유지 |
| Agent 삭제 | 구현 | 유지 |
| Agent 이름 | 구현 | 유지 |
| 모델 ID 직접 지정 | 구현 | 유지 |
| System Prompt | 구현 | 유지 |
| Agent별 파일 참고자료 | 구현 | 유지 |
| Agent별 Notion 참고자료 | 구현 | 유지 |
| 파일 + Notion 통합 Top-K 검색 | 구현 | 유지 |
| 동일 Agent를 Hierarchical Worker로 중복 추가 | 가능 | 유지 |

## 2.2 파일/RAG

- 지원 형식: PDF, DOCX, PPTX, XLSX, CSV, TXT, MD
- 파일 SHA-256 기반 메타데이터 관리
- 텍스트 추출
- Chunk 분할
- OpenAI embedding 생성
- cosine similarity 기반 Top-K 검색
- Agent별 최대 chunk 보호 한도
- RAG 검색 출처 및 similarity 기록
- 실행 시 별도 업로드 파일을 하나 이상의 Target에 라우팅
- 실행 파일과 영구 Agent 참고자료를 구분

**Migration 원칙:** 텍스트 추출/RAG 계산은 UI와 분리한다. Embedding cache는 영구 비즈니스 데이터가 아니므로 재생성 가능한 cache로 취급한다.

## 2.3 Notion 참고자료

- Integration Token 기반 read-only 연결
- Page URL / Database URL / raw Notion ID 지원
- Page markdown 조회
- Database → data source → page 조회
- 일부 DB property를 텍스트로 정규화
- Page/Database/Data source 자동 판별
- Notion source cache
- Notion content + local file을 하나의 RAG corpus로 검색
- Token은 Workspace ZIP에 저장하지 않음

**현재 한계:** Notion write-back, OAuth, webhook, live sync는 없음.

## 2.4 Linear Workflow

- Agent 순차 배치
- Step 순서 변경
- Step 삭제
- Step별 `additional_prompt`
- 이전 Agent Output → 다음 Agent Input 전달
- 옵션에 따라 최초 사용자 요청을 후속 Step에도 포함
- Step별 실행 파일 라우팅
- 실행 결과 / Token usage / RAG source 기록

## 2.5 Hierarchical Workflow

- Manager 1명
- Worker N명
- Worker별 `additional_prompt`
- Manager planning prompt
- Manager synthesis prompt
- Manager routing prompt
- Manager가 다음 실행 round를 JSON 계획으로 생성
- Worker role에 따라 작업 배분
- Worker Output을 Artifact로 저장
- Artifact dependency 검증
- 사용자 후속 피드백 처리
- Revision 생성
- Manager와 지속 대화

## 2.6 Dependency-aware 자기소개서 Workflow 규칙

현재 코드에는 범용 Hierarchical Engine과 별개로 자기소개서 Workflow의 업무 규칙이 직접 결합되어 있다.

Artifact kind:

```text
intake
analysis
candidates
selection_review
strategy
draft
review
```

핵심 dependency:

```text
candidates       <- intake + analysis
selection_review <- newest candidates only
strategy         <- candidates + selection_review
draft            <- strategy
review           <- newest draft only
```

W1~W6 역할명이 모두 존재하면 현재 Validator는 역할과 Artifact kind를 추가로 강제한다.

```text
W1 -> intake
W2 -> analysis
W3 -> candidates / strategy
W4 -> draft
W5 -> review
W6 -> selection_review / review
```

또한 다음 안전 규칙이 있다.

- `selection_review`는 다른 Artifact가 섞이지 않도록 최신 candidates만 받음
- review는 최신 draft 하나만 받음
- Writer가 자신의 Draft를 최종 review할 수 없음
- draft는 독립 round에서 실행
- dependency가 기계적으로 복구 가능한 경우 자동 정규화
- 계획 검증 실패가 연속될 경우 제한된 횟수만 재계획
- 모든 검토가 통과하지 않으면 Manager가 임의로 Final 처리하지 않도록 제한

**2.0 개선 대상:** 이 규칙을 범용 Engine에서 분리해 `career_cover_letter` 정책/Workflow 정의로 옮긴다.

## 2.7 Checkpoint / Resume

현재 stable 구조에는 Streamlit session 기반 resumable job controller가 존재한다.

- `managed_job` 생성
- planning / executing phase
- assignment cursor
- W1 intake의 30,000자 단위 map batch checkpoint
- API timeout 및 retry 제한
- 오류 분류
- pause / retry / cancel
- 각 script execution에서 한 checkpoint만 전진
- `st.rerun()`으로 다음 checkpoint 진행
- 완료된 Artifact는 세션 내 유지

이 구조는 2.0 LangGraph 전환 시 **동작 요구사항으로 유지하되 구현은 폐기**한다. 2.0에서는 LangGraph + 영구 checkpointer가 같은 책임을 갖는다.

## 2.8 Revision / History

- 최초 결과 Revision v1
- 사용자 피드백 → 후속 Revision
- Revision별 feedback
- routing 정보
- Worker output
- final output
- 실행 Step 기술정보
- 현재 결과와 과거 Revision 조회
- JSON export

## 2.9 Workspace 저장/복구

- `agent_workspace.zip` 저장
- schema version 1~4 backward import
- Agent 설정 저장
- RAG 원본 파일 ZIP 포함
- Notion source reference 저장
- Linear Workflow 저장
- Hierarchical Workflow 저장
- Manager prompt 저장
- Git repo의 `agent_workspace.zip` 자동 불러오기

저장하지 않는 정보:

- OpenAI API Key
- Notion Integration Token
- 실행 결과
- 대화/Revision history
- Notion fetched content/cache
- RAG embedding cache

---

# 3. 현재 Agent 데이터 모델

현재 Agent는 `st.session_state.agents[agent_id]`에 dict로 저장된다.

```python
Agent = {
    "id": str,
    "name": str,
    "model": str,
    "system_prompt": str,
    "rag_enabled": bool,
    "rag_top_k": int,
    "rag_files": [
        {
            "name": str,
            "bytes": bytes,
            "sha256": str,
            "size": int,
        }
    ],
    "notion_enabled": bool,
    "notion_sources": [str],
}
```

### 2.0 목표

- Agent configuration은 UI/session이 아닌 Core Model로 정의한다.
- `rag_files[].bytes`는 Agent 객체 안에 직접 들고 있지 않는다.
- 파일 metadata와 source relation은 DB에 저장한다.
- 실제 파일 payload는 content-addressed local storage(`data/sources/<sha256>`)에 저장하는 것을 기본안으로 한다.
- Secret은 Agent model에 포함하지 않는다.

---

# 4. 현재 Workflow 데이터 모델

## 4.1 Linear

```python
workflow = [
    {
        "step_id": str,
        "agent_id": str,
        "additional_prompt": str,
    }
]

include_original_prompt: bool
```

## 4.2 Hierarchical

```python
hierarchy = {
    "manager_agent_id": str | None,
    "manager_planning_prompt": str,
    "manager_synthesis_prompt": str,
    "manager_routing_prompt": str,
    "workers": [
        {
            "worker_id": str,
            "agent_id": str,
            "additional_prompt": str,
        }
    ],
}
```

### 주의

`worker_id`와 `agent_id`는 다른 개념이다. 동일 Agent를 여러 Worker slot에 넣을 수 있으므로 2.0에서도 이 구분을 유지해야 한다.

### 2.0 목표

범용 Workflow definition과 특정 Workflow policy를 분리한다.

```text
Workflow
├─ mode: linear | hierarchical | graph
├─ nodes/worker slots
├─ prompts/config
└─ policy_id(optional)
```

자기소개서의 W1~W6 강제 규칙은 일반 Workflow 데이터 모델에 하드코딩하지 않는다.

---

# 5. 현재 Session / Run 데이터 모델

Hierarchical Run 시작 시 생성되는 session의 핵심 구조:

```python
session = {
    "session_id": str,
    "original_user_prompt": str,
    "manager_agent_id": str,
    "manager_name": str,
    "workers": list,
    "chat_history": list,
    "latest_worker_outputs": dict,
    "revisions": list,
    "current_final_output": str,
    "execution_context_by_target": dict,
    "execution_filenames_by_target": dict,
    "manager_planning_prompt": str,
    "manager_synthesis_prompt": str,
    "manager_routing_prompt": str,
    "engine": dict,
    "managed_job": dict | None,
    "last_managed_job": dict | None,
}
```

`last_run`은 UI 표시용 snapshot 역할도 수행하며 Linear/Hierarchical의 구조가 서로 다르다.

### 문제점

- Run state와 UI render state가 같은 session_state에 섞임
- 앱 프로세스가 완전히 재시작되면 영구 복구 불가
- 일부 데이터는 중복 저장됨(`latest_worker_outputs`, Artifact output, Revision worker outputs 등)
- Runtime state와 audit/history state 경계가 약함

### 2.0 목표

```text
Run        = 실행의 정체성과 현재 상태
Message    = 사용자/Manager 대화
Artifact   = Worker가 생성한 불변 산출물
Revision   = 사용자에게 보인 버전
Checkpoint = 그래프 복구 위치/상태
Event      = 실행 로그
RunFile    = 실행 시 업로드한 파일과 Target routing
```

UI용 snapshot은 DB 원본에서 projection하여 생성한다.

---

# 6. 현재 Artifact / Revision / Job 데이터 모델

## 6.1 Artifact

현재 `engine["artifacts"][artifact_id]` 구조:

```python
Artifact = {
    "kind": str,
    "worker_id": str,
    "worker_name": str,
    "output": str,
    "depends_on": [artifact_id],
    "draft_version": int,
    "counts": list,
}
```

### 2.0 원칙

- 생성 후 Artifact body를 수정하지 않는다.
- 수정 결과는 새 Artifact로 생성한다.
- dependency는 별도 relation으로 조회 가능해야 한다.
- Artifact ID는 안정적인 UUID 사용을 권장한다.

## 6.2 Revision

```python
Revision = {
    "revision": int,
    "kind": "initial" | "feedback",
    "title": str,
    "feedback": str,
    "routing": dict | None,
    "worker_outputs": dict,
    "final_output": str,
    "steps": list,
}
```

Revision은 사용자 관점의 결과 버전이며 Artifact와 동일 개념이 아니다. 이 구분을 2.0 DB에서도 유지한다.

## 6.3 Managed Job

현재 resumable job 핵심 필드:

```python
ManagedJob = {
    "job_id": str,
    "kind": str,
    "feedback": str,
    "base_revision": int,
    "active": bool,
    "paused": bool,
    "phase": str,
    "round_count": int,
    "validation_error": str,
    "pending_plan": dict | None,
    "pending_assignments": list,
    "assignment_cursor": int,
    "assignment_state": dict | None,
    "revisions_used": int,
    "steps": list,
    "decisions": list,
    "outputs": dict,
    "dependency_repairs": list,
    "error": str,
    "error_type": str,
    "terminal_message": str,
    "terminal_status": str,
    "last_checkpoint": str,
    "started_at": float,
}
```

이 필드들은 LangGraph Migration 시 그대로 DB schema로 복사하는 것이 아니라, **필드가 담당하는 의미를 Graph State / Checkpoint / Event로 재배치**한다.

---

# 7. RAG / Notion 구조와 Migration 기준

## 현재 RAG flow

```text
Agent source 설정
→ 파일/Notion 텍스트 추출
→ chunk_text
→ embedding
→ normalized vector cache
→ query embedding
→ cosine similarity
→ Top-K context
→ Agent call
```

## 현재 cache

```text
rag_cache[corpus_signature]
notion_cache[token fingerprint + epoch + source id]
```

이 cache들은 프로세스 재시작 시 사라져도 재생성 가능하므로 **영구 domain data가 아니다.**

## 2.0 분리 기준

```text
retrieval/
├─ extractors.py
├─ chunking.py
├─ embeddings.py
└─ rag.py

integrations/
└─ notion.py
```

Notion Integration 함수는 `st.session_state`에서 Token/cache를 직접 읽지 않고 명시적 dependency를 전달받아야 한다.

---

# 8. Streamlit 종속 코드 분류

다음은 2.0 Core에서 제거되어야 하는 Streamlit 의존 영역이다.

## UI 전용 — Core로 이동하지 않음

- `st.set_page_config`
- CSS / HTML styling
- Sidebar
- tabs
- form / button / text_area / selectbox / file_uploader
- progress / status / expander
- chat_message / chat_input
- download_button
- `st.error`, `st.warning`, `st.info`, `st.success`
- Revision timeline rendering

## State coupling — Interface로 대체

- `st.session_state.agents`
- `st.session_state.workflow`
- `st.session_state.hierarchy`
- `st.session_state.rag_cache`
- `st.session_state.notion_cache`
- `st.session_state.last_run`
- `st.session_state.hierarchical_session`

## Control-flow coupling — LangGraph/FastAPI로 대체

- `st.rerun()`을 workflow progression에 사용
- `st.stop()`을 runtime stop에 사용
- one-tick-per-rerun managed job driver
- UI render 함수 안에서 Agent call 수행

## 현재 Core 후보이나 Streamlit dependency 제거가 필요한 함수군

- Workspace serialize/deserialize
- file text extraction
- chunking
- Notion API client
- Notion source resolver
- embedding/RAG
- `call_agent`
- `execute_agent_stage`
- plan JSON parsing
- dependency stabilization/validation
- Manager planning payload
- Worker execution
- Draft/review contracts
- error classification

---

# 9. Core로 이동할 코드와 모듈 책임

STEP 1에서 아래와 같이 분리하는 것을 기준 구조로 사용한다.

```text
src/agent_workflow_studio/
├─ core/
│  ├─ models.py
│  ├─ agents.py
│  ├─ workflow.py
│  ├─ artifacts.py
│  ├─ dependency.py
│  ├─ execution.py
│  └─ errors.py
│
├─ retrieval/
│  ├─ extractors.py
│  ├─ chunking.py
│  ├─ embeddings.py
│  └─ rag.py
│
├─ integrations/
│  ├─ openai_client.py
│  └─ notion.py
│
├─ persistence/
│  ├─ interfaces.py
│  └─ memory.py          # STEP 1용, SQLite는 STEP 2
│
├─ policies/
│  └─ career_cover_letter.py
│
├─ graph/                # STEP 3에서 추가
├─ api/                  # STEP 5에서 추가
└─ migration/
   └─ workspace_v4.py

ui/                      # STEP 6
integrations_discord/    # STEP 7

tests/
docs/
data/                    # gitignore 대상

app.py                   # Migration 동안 frozen legacy reference
agent_workspace.zip      # legacy import fixture/reference
```

### STEP 1에서 지켜야 할 경계

- LangGraph 아직 도입하지 않음
- FastAPI 아직 도입하지 않음
- React/Tauri 아직 도입하지 않음
- 기존 `app.py`를 삭제하거나 rewrite하지 않음
- 순수 Python Core에 `import streamlit` 금지

---

# 10. 개선이 필요한 기존 구조

## P0 — Migration 전 반드시 보존/분리

### 10.1 UI와 Engine 결합

현재 Agent 호출, state mutation, checkpoint progression, UI rendering이 동일 `app.py`와 동일 Streamlit 프로세스에 있다.

**2.0:** Core 함수는 입력값과 repository/service dependency만 받아야 하며 UI 상태를 직접 참조하지 않는다.

### 10.2 Session State 영속성

현재 checkpoint는 단순 rerun에는 강하지만 프로세스/컨테이너가 완전히 종료되면 복구되지 않는다.

**2.0:** SQLite + LangGraph persistent checkpoint로 이전.

### 10.3 범용 Engine과 자기소개서 W1~W6 규칙 결합

현재 `validate_plan`이 Worker 이름 `W1`~`W6`을 파싱하여 특정 kind를 강제한다.

**2.0:** `career_cover_letter` policy로 분리.

### 10.4 RAG/Notion cache의 global session dependency

현재 retrieval과 Notion resolver가 Streamlit cache state에 직접 연결된다.

**2.0:** Cache interface 주입. 없는 경우에도 기능이 동작해야 함.

## P1 — STEP 2~4에서 개선

### 10.5 데이터 중복

Artifact output / latest_worker_outputs / Revision worker_outputs / Step output에 동일 payload가 중복될 수 있다.

**2.0:** Artifact를 source of truth로 두고 Revision/Event는 Artifact ID를 참조하는 방향을 우선 검토.

### 10.6 ID 의미 혼재

`session_id`, `job_id`, `worker_id`, `agent_id`, `step_id`, artifact의 `a1` 형태 ID가 함께 사용된다.

**2.0:** UUID 기반 Entity ID와 사용자 표시 순번을 분리.

### 10.7 Manager context와 Worker context 경계

현재 Manager planning context는 preview로 경량화되었지만 이 로직은 runtime 함수 내부에 존재한다.

**2.0:** Context builder를 별도 service로 분리하고 테스트 가능하게 유지.

### 10.8 Secret 관리

Workspace ZIP에는 Token을 저장하지 않는 정책은 올바르다. 다만 현재 OpenAI Key는 UI 입력, Notion은 UI 또는 Streamlit Secret이다.

**2.0:** 환경변수/OS secret/config provider를 사용하고 DB, log, export에 secret을 절대 저장하지 않는다.

## P2 — 후속 단계

- Notion write-back: STEP 8
- Discord interaction: STEP 7
- Tauri/Desktop packaging: STEP 9
- OAuth/Webhook: 필요 시 STEP 8 이후

---

# 11. Workspace v4 → 2.0 데이터 Migration 매핑

현재 ZIP manifest:

```text
manifest.json
├─ schema_version
├─ app
├─ agents
├─ workflow
├─ include_original_prompt
├─ workflow_mode
└─ hierarchy

rag_files/<agent_id>/<file>
```

## 11.1 Agent

| Workspace v4 | 2.0 target |
|---|---|
| `agents.*.id` | `agents.id` |
| `name` | `agents.name` |
| `model` | `agents.model` |
| `system_prompt` | `agents.system_prompt` |
| `rag_enabled` | Agent retrieval config |
| `rag_top_k` | Agent retrieval config |
| `rag_files` metadata | `sources` / `agent_sources` |
| RAG bytes | `data/sources/<sha256>` |
| `notion_enabled` | Agent retrieval config |
| `notion_sources` | `sources(type=notion)` / `agent_sources` |

## 11.2 Linear Workflow

| Workspace v4 | 2.0 target |
|---|---|
| `workflow[]` | `workflow_steps` |
| `step_id` | `workflow_steps.id` |
| `agent_id` | Agent FK |
| `additional_prompt` | Step config |
| `include_original_prompt` | Workflow config |

## 11.3 Hierarchical Workflow

| Workspace v4 | 2.0 target |
|---|---|
| `hierarchy.manager_agent_id` | workflow manager relation |
| `hierarchy.workers[]` | workflow worker slots |
| `worker_id` | worker slot ID |
| `worker.agent_id` | Agent FK |
| `worker.additional_prompt` | worker slot config |
| manager planning/synthesis/routing prompts | workflow config |

## 11.4 저장되지 않던 Run 정보

기존 Workspace v4에는 Run/Revision/Message/Checkpoint가 포함되지 않는다. 따라서 과거 `agent_workspace.zip`만으로 이전 실행기록을 복구할 수 없다.

2.0부터는 다음을 SQLite에 영구 저장한다.

```text
runs
messages
artifacts
artifact_dependencies
revisions
checkpoints
execution_events
run_files
run_file_targets
```

---

# 12. 데이터 손실 및 호환성 Risk Register

| 위험 | 영향 | 대응 |
|---|---|---|
| Workspace v4 RAG bytes 누락 | Agent 참고자료 손실 | ZIP import 시 hash 검증 후 local source storage로 복사 |
| 동일 Agent를 여러 Worker로 사용 | Worker별 추가 prompt 손실 가능 | worker slot ID를 Agent ID와 별도 유지 |
| Notion Token을 데이터로 migration | Secret 유출 | 절대 migration하지 않음 |
| 기존 Notion fetched cache를 보존하려 함 | stale data 위험 | cache는 migration하지 않고 재조회 |
| `a1`, `a2` Artifact ID를 영구 ID로 사용 | Run 간 충돌 | UUID + display sequence 분리 |
| session state를 DB에 그대로 dump | UI 임시 state까지 영구화 | Domain model만 저장 |
| 기존 Revision과 Artifact를 같은 entity로 통합 | History 의미 손실 | 두 모델을 분리 유지 |
| W1~W6 규칙을 generic engine에 유지 | 다른 Workflow 확장 어려움 | policy module로 분리 |
| 실행 파일 routing 미이전 | Worker 입력 차이 발생 | `run_files` + `run_file_targets`로 보존 |
| API/RAG error가 UI 문자열에만 존재 | 재시도/자동화 어려움 | typed error + execution event 저장 |
| `DEFAULT_MANAGER_REVISION_PROMPT` 등 legacy 상수 | 정책 혼동 | 실제 사용처 확인 후 STEP 1에서 legacy 표시, 즉시 삭제 금지 |

---

# 13. 유지 / 개선 / 폐기 / 후순위 판정

## 유지

- Agent configuration 의미
- System Prompt
- 파일 RAG
- Notion read-only source
- Linear Workflow
- Hierarchical Manager/Worker
- Worker slot 중복 가능 구조
- Step/Worker additional prompt
- 실행 파일 multi-target routing
- Artifact/dependency 개념
- candidates → independent selection → strategy → draft → review 정책
- Revision/history
- human feedback
- Workspace v1~v4 import compatibility
- Secret 미저장 원칙

## 개선

- Streamlit state → repository/persistence
- checkpoint/resume → LangGraph persistent checkpointer
- Manager context builder 분리
- typed model 도입
- typed error 도입
- Artifact/Revision 중복 payload 축소
- source/file storage 분리
- 자기소개서 policy와 generic engine 분리
- API timeout/retry/error event 구조화

## 폐기 예정 구현

기능 자체가 아니라 **구현 방식**을 폐기한다.

- `st.rerun()` 기반 workflow progression
- `st.session_state`를 domain database처럼 사용하는 구조
- UI 함수 내부 직접 Agent execution
- Git에 `agent_workspace.zip`을 두어 앱 부팅 상태를 구성하는 방식

`agent_workspace.zip` 자체는 **legacy import format**으로 계속 지원한다.

## 후순위

- FastAPI: STEP 5
- React Local UI: STEP 6
- Discord: STEP 7
- Notion write/inbox: STEP 8
- Tauri/Desktop package: STEP 9

---

# 14. 2.0 목표 Runtime Architecture

```text
                    ┌──────────────┐
                    │ Local UI     │
                    └──────┬───────┘
                           │
Discord ─────┐             │
             ▼             ▼
        ┌──────────────────────┐
        │       FastAPI        │
        └──────────┬───────────┘
                   │
              ┌────▼─────┐
              │ LangGraph│
              └────┬─────┘
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
   Core Engine    SQLite    Retrieval
       │                       │
       ▼                       ├─ Files
     OpenAI                    └─ Notion
```

### 책임 분리

```text
UI            : 표시/입력만
FastAPI       : 외부 interface와 Run command
LangGraph     : state transition / interrupt / resume
Core          : Agent/Artifact/Dependency/Policy 규칙
Persistence   : Run/Artifact/Revision/Checkpoint 저장
Retrieval     : 파일/Notion 검색 context
Integrations  : OpenAI/Notion/Discord adapter
```

---

# 15. STEP별 Migration Gate

```text
STEP 0  Baseline / Migration Spec
  ↓
STEP 1  Pure Python Core
  ↓
STEP 2  SQLite Persistence
  ↓
STEP 3  LangGraph Checkpoint + Interrupt/Resume
  ↓
STEP 4  기존 자기소개서 Hierarchical Workflow 완전 이식
  ↓
STEP 5  FastAPI
  ↓
STEP 6  Local UI
  ↓
STEP 7  Discord
  ↓
STEP 8  Notion Interaction
  ↓
STEP 9  Desktop / Final QA
```

다음 STEP을 미리 구현하지 않는다. 각 Gate는 해당 단계의 Checkpoint PASS 후에만 진행한다.

---

# 16. STEP 0 Checkpoint 판정

## CP0-1 기존 기능이 전부 목록화됐는가?

**PASS**

Agent, RAG, Notion, Linear, Hierarchical, dependency-aware career workflow, checkpoint/resume, revision, workspace, execution-file routing을 Migration baseline에 포함했다.

## CP0-2 Streamlit 전용 기능과 Core 기능이 구분됐는가?

**PASS**

UI-only / state coupling / control-flow coupling / Core candidate로 분리했다.

## CP0-3 기존 Workspace 데이터 손실 위험이 파악됐는가?

**PASS**

Workspace schema v4 필드와 2.0 target mapping, RAG bytes, Notion secret/cache, worker slot, run history 부재 등 주요 migration risk를 정의했다.

## CP0-4 새로운 프로젝트 폴더 구조가 결정됐는가?

**PASS**

`src/agent_workflow_studio` 아래 Core/Retrieval/Integrations/Persistence/Policies를 분리하고, 이후 Graph/API/UI를 단계적으로 추가하는 구조를 기준안으로 확정했다.

---

# STEP 0 RESULT

```text
STEP 0: PASS
NEXT: STEP 1 — Core Engine 분리
```

STEP 1에서는 기존 `app.py`를 frozen reference로 유지한 상태에서, Streamlit import가 전혀 없는 Pure Python Core를 생성한다. LangGraph, FastAPI, React는 아직 추가하지 않는다.
