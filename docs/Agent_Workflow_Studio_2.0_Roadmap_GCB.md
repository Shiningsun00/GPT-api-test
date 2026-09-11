# Agent Workflow Studio 2.0 — Roadmap & GCB v1.1

> 상태: **ACTIVE**  
> 버전: **v1.1**  
> 기준: `docs/PRD.md` APPROVED v1.0 + `docs/migration_spec.md`  
> 목표: Streamlit 결합형 프로토타입을 Local-first 범용 Multi-Agent Workflow Studio로 단계적으로 이식한다.

---

# 0. Source of Truth

구현 우선순위는 아래 순서를 따른다.

```text
1. docs/PRD.md                = 제품 요구사항 / 최종 승인 기준
2. docs/migration_spec.md     = 현재 시스템 baseline / migration 기준
3. 이 Roadmap & GCB           = 단계별 실행 계획 / checkpoint
4. GitHub Issue               = 현재 STEP의 실제 작업 단위
```

문서 간 충돌이 있으면 PRD를 우선하고, 제품 방향이 바뀌면 먼저 PRD Decision Log를 수정한 후 Roadmap/Issue를 갱신한다.

---

# 1. Target Architecture

```text
Local UI / Discord / Notion
            ↓
         FastAPI
            ↓
         LangGraph
            ↓
   Core Domain / Policies
      ↙       ↓       ↘
  OpenAI    SQLite   Retrieval
                     ↙      ↘
                Local File  Notion
```

장기적으로 Local UI는 Tauri 패키징을 검토한다.

---

# 2. Approved Product Decisions

PRD v1.0에서 다음을 확정했다.

```text
- Single-user / Local-first
- 2.0은 OpenAI only, provider interface는 교체 가능하게 설계
- STEP 6 UI는 Form/List 우선, Visual Node Editor는 후속
- 초기에는 Active Run 1개
- 프로그램 재시작 후 자동 실행 금지, Manual Resume
- legacy agent_workspace.zip은 Import only
- Notion 생성/append/지정영역 update 허용, 삭제/대규모 overwrite는 명시 승인
- Session/Run/Artifact/Revision/Message/Attachment는 사용자 삭제 전까지 보존
- Discord: 시작/상태/HITL/Resume/Follow-up/결과 수신
- Notion: Source + Ready Inbox + Final Output 저장
- Manager 결과 이후 사용자 Follow-up + 파일 첨부 MUST
```

---

# 3. Cross-cutting Invariants

모든 STEP에서 다음 규칙을 유지한다.

```text
- Workflow Session과 Run을 같은 개념으로 합치지 않는다.
- Agent-requested HITL은 같은 Active Run을 Resume한다.
- Manager 결과 이후 User Follow-up은 같은 Session의 새 Continuation Run을 만든다.
- Follow-up 파일은 기본 Turn-scoped이며 영구 Agent RAG로 자동 승격하지 않는다.
- 사용자 Follow-up과 첨부파일은 LLM 호출 전에 저장 가능한 구조여야 한다.
- 기존 Artifact와 Revision은 덮어쓰지 않는다.
- 완료된 Worker/Node를 이유 없이 재실행하지 않는다.
- Worker output을 system instruction으로 승격하지 않는다.
- Secret은 Git/SQLite 일반 데이터/Export/Log에 저장하지 않는다.
- 한 번에 Active Run 1개를 기본으로 한다.
- 재시작 시 자동 API 실행 금지, 사용자가 Resume한다.
- 기존 app.py는 Migration 완료 전 frozen legacy reference다.
- 다음 STEP 기능을 미리 구현하지 않는다.
- 검증하지 못한 항목은 PASS로 표시하지 않는다.
```

---

# 4. Milestone Overview

```text
STEP 0  Existing System Freeze / Migration Spec      [PASS]
STEP 1  Pure Python Core Extraction                  [ACTIVE]
STEP 2  SQLite Domain Persistence                    [PENDING]
STEP 3  LangGraph Durable State Machine              [PENDING]
STEP 4  Career Cover Letter Workflow Migration       [PENDING]
STEP 5  FastAPI Service Boundary                     [PENDING]
STEP 6  Local UI                                     [PENDING]
STEP 7  Discord Integration                          [PENDING]
STEP 8  Notion Interaction                           [PENDING]
STEP 9  Desktop / Migration / Final QA               [PENDING]
```

---

# STEP 0 — Existing System Freeze / Migration Spec

## Goal

기존 Streamlit 앱의 기능, 데이터 모델, RAG/Notion, Workflow, Workspace, Checkpoint 구조를 분석해 migration baseline을 만든다.

## Context

기존 `app.py`는 Agent 관리, RAG, Notion read-only, Linear/Hierarchical Workflow, Revision, checkpoint-like resume, Workspace ZIP 기능을 하나의 Streamlit 프로세스 안에서 수행한다.

## Boundary

- 기능 변경 금지
- 신규 Framework 도입 금지
- 기존 app.py rewrite 금지

## Deliverable

`docs/migration_spec.md`

## Checkpoint

```text
[x] 기존 기능 목록화
[x] Streamlit UI / Core 책임 분리
[x] Workspace migration risk 파악
[x] 2.0 target project structure 결정
```

## Result

**PASS**

---

# STEP 1 — Pure Python Core Extraction

## Goal

기존 Streamlit 앱에서 UI에 종속되지 않는 Domain/Core/Retrieval/Integration boundary를 분리한다.

## Context

- STEP 0 PASS
- PRD v1.0 APPROVED
- 이후 SQLite/LangGraph/FastAPI가 Core 위에 올라갈 예정
- 이번 STEP에서는 영속 실행 엔진을 완성하는 것이 아니라, 테스트 가능한 순수 Python 기반을 만드는 것이 목적

## Target Structure

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
├─ retrieval/
│  ├─ extractors.py
│  ├─ chunking.py
│  ├─ embeddings.py
│  └─ rag.py
├─ integrations/
│  ├─ openai_client.py
│  └─ notion.py
├─ persistence/
│  ├─ interfaces.py
│  └─ memory.py
├─ policies/
│  └─ career_cover_letter.py
└─ migration/
   └─ workspace_v4.py
```

## Required Domain Models

최소 다음 개념을 UI state에서 분리한다.

```text
Agent
Workflow
WorkflowNode / WorkerSlot
WorkflowSession
Run
Message
MessageAttachment
Artifact
ArtifactDependency
Revision
ExecutionFile / RunFile
```

### Session / Run invariant

```text
WorkflowSession S1
├─ Run R1 — 최초 요청
├─ Run R2 — 완료 결과 이후 Follow-up
└─ Run R3 — Follow-up + 파일
```

Agent가 실행 도중 질문한 경우에는 새 Run을 만들지 않고 현재 Active Run을 Resume한다.

## OpenAI Boundary

2.0 구현은 OpenAI만 지원하되 Core가 OpenAI SDK 객체에 직접 결합되지 않도록 호출 인터페이스를 분리한다.

```text
Core → ModelProvider interface → OpenAI adapter
```

## Follow-up Attachment Boundary

STEP 1에서는 실제 SQLite 저장은 하지 않지만, 향후 아래 관계를 저장할 수 있는 모델/interface를 준비한다.

```text
Message
└─ MessageAttachment
   ├─ filename
   ├─ sha256
   ├─ size
   ├─ storage reference
   └─ scope = turn/run
```

첨부파일은 기본적으로 permanent Agent RAG source와 구분한다.

## GCB

### Goal

Streamlit에 종속되지 않는 Agent Workflow Studio Core package를 생성한다.

### Context

현재 `app.py`의 Agent, Workflow, Artifact, dependency, file extraction, RAG, OpenAI, Notion 관련 로직을 기능 의미를 유지한 채 분리한다. PRD v1.0의 Session/Run, HITL Follow-up, Attachment 요구사항을 이후 단계에서 구현할 수 있도록 domain boundary에 반영한다.

### Boundary

```text
- app.py 수정 금지
- LangGraph 도입 금지
- SQLite 구현 금지
- FastAPI 도입 금지
- React/Tauri 작업 금지
- Core package 내부 import streamlit 금지
- 자기소개서 W1~W6 규칙을 generic engine에 하드코딩 금지
- OpenAI만 구현하되 provider interface는 교체 가능하게 유지
- Message/Attachment 모델을 Session/Run과 분리
- Run-only attachment와 permanent RAG source를 동일 entity로 취급하지 않음
- 기존 기능 임의 삭제 금지
```

## Checkpoint

```text
[ ] CP1-1 src/agent_workflow_studio 패키지 생성
[ ] CP1-2 Core/Retrieval/Integrations package에 streamlit import 0개
[ ] CP1-3 Agent/Workflow/WorkflowSession/Run/Message/MessageAttachment/Artifact/Revision 모델 분리
[ ] CP1-4 동일 Session 내 Initial Run / Continuation Run 관계를 모델로 표현 가능
[ ] CP1-5 dependency validation/normalization을 UI 없이 호출 가능
[ ] CP1-6 file extraction/chunking을 UI 없이 테스트 가능
[ ] CP1-7 Run-only attachment와 permanent RAG source가 타입/모델 수준에서 구분됨
[ ] CP1-8 OpenAI adapter가 provider boundary 뒤에 위치
[ ] CP1-9 Notion 함수가 st.session_state 없이 명시적 config/token/cache dependency를 받음
[ ] CP1-10 career cover letter 규칙이 generic Core와 분리 가능한 policy boundary에 있음
[ ] CP1-11 unit/static tests 통과
[ ] CP1-12 기존 app.py 변경 없음
```

## Gate

모든 CP1 항목 PASS 후 STEP 1 PR을 생성한다.

---

# STEP 2 — SQLite Domain Persistence

## Goal

프로그램 종료 후에도 Agent/Workflow/Session/Run/Message/Attachment/Artifact/Revision/Event가 복구되도록 Domain Persistence를 구축한다.

## Important Boundary

**STEP 2는 Domain durability를 구현한다. 정확한 Graph Node checkpoint/resume는 STEP 3 LangGraph 책임이다.**

SQLite에 LangGraph를 흉내 내는 자체 graph checkpointer를 만들지 않는다.

## Required Storage

```text
agents
sources
agent_sources
workflows
workflow_nodes / workflow_workers
workflow_sessions
runs
messages
message_attachments
artifacts
artifact_dependencies
revisions
execution_events
run_files
run_file_targets
external_thread_links
```

원본 파일은 기본적으로 로컬 파일 저장소에 보관하고 DB에는 metadata/path/hash를 기록한다.

## GCB

### Goal

Core Domain Entity를 SQLite에 저장하고 재실행 후 rehydrate할 수 있게 한다.

### Context

STEP 1 Pure Python Core가 완성되어 있다. PRD는 Follow-up 명령과 Attachment를 LLM 호출 전에 보존할 수 있어야 한다고 요구한다.

### Boundary

```text
- LangGraph checkpoint 구현 금지
- Secret 평문 DB 저장 금지
- 파일 bytes를 무조건 DB blob으로 밀어 넣지 않음
- 사용자 Follow-up/Attachment는 실행 요청 전에 durable write 가능해야 함
- terminal Run state를 Follow-up 때문에 다시 RUNNING으로 변경하지 않음
```

## Checkpoint

```text
[ ] Agent/Workflow 저장 후 프로세스 재시작 복구
[ ] WorkflowSession + 여러 Run 관계 복구
[ ] Message + Attachment 관계 복구
[ ] Follow-up 명령/파일 durable write
[ ] Artifact dependency / Revision 이력 복구
[ ] Run/Event 상태 복구
[ ] Secret이 DB에 없음
[ ] schema migration/versioning 존재
[ ] unit/integration test 통과
```

---

# STEP 3 — LangGraph Durable State Machine

## Goal

기존 Manager loop를 LangGraph 기반 상태 머신으로 대체하고 Checkpoint/Interrupt/Resume를 구현한다.

## Graph State 최소 요소

```text
session_id
run_id
user_request
follow_up_message
follow_up_attachment_refs
current_stage
artifacts
messages
draft_version
review_status
waiting_for_user
```

## HITL 두 종류

### Agent-requested HITL

```text
Active Run
→ interrupt()
→ WAITING_FOR_USER
→ Command(resume=...)
→ 같은 Run 계속
```

### User-initiated Post-result Follow-up

```text
Completed Run / Revision vN
→ User Follow-up + optional files
→ 같은 Session 아래 Continuation Run 생성
→ 새 Graph execution
→ Revision vN+1
```

## GCB

### Goal

Workflow 실행을 durable LangGraph state machine으로 전환한다.

### Boundary

```text
- typed graph state 사용
- persistent checkpointer 사용
- 완료 Artifact 불변
- duplicate worker 방지
- WAITING_FOR_USER는 정상 상태
- Follow-up 파일은 reference로 state에 전달
- restart 후 자동 resume 금지
```

## Checkpoint

```text
[ ] 정상 실행 완료
[ ] Worker 오류 후 checkpoint resume
[ ] 프로세스 종료 후 manual resume
[ ] interrupt → user answer → same Run resume
[ ] completed result → follow-up → continuation Run
[ ] follow-up attachment reference 전달
[ ] 완료 Node 불필요 재실행 없음
[ ] 중복 Artifact 없음
```

---

# STEP 4 — Career Cover Letter Workflow Migration

## Goal

기존 W1~W6 자기소개서 Hierarchical Workflow를 generic Core + LangGraph 위의 Domain Policy/Template로 완전히 이식한다.

## Required Flow

```text
W1 Evidence Intake + W2 Company/Job Analysis
                ↓
        W3 Candidates
                ↓
      W6 Selection Review
                ↓
          W3 Strategy
                ↓
           W4 Draft
                ↓
        ┌───────┴───────┐
      W5 Review       W6 Review
        └───────┬───────┘
                ↓
             Manager
           ↙           ↘
       Revise           Final
```

## Follow-up Flow

```text
Manager Revision vN
→ User command + optional file
→ Continuation Run
→ Manager routing
→ 필요한 Worker만 재실행
→ 새 Artifact
→ 필요한 Review 재실행
→ Revision vN+1
```

## Boundary

```text
- selection_review는 candidates만
- review는 최신 draft만
- W4 self final-review 금지
- 자동 수정 최대 2회
- 사용자 질문 최대 3개
- 기존 사실 검증 규칙 유지
- Follow-up이 기존 Artifact/Revision을 덮어쓰지 않음
```

## Checkpoint

```text
[ ] W1→W2→W3→W6→W3→W4→W5/W6→Manager 정상 완료
[ ] needs_input interrupt 동작
[ ] user answer 후 same Run resume
[ ] Manager 결과 후 Follow-up continuation Run
[ ] Follow-up 파일을 근거로 필요한 Worker만 재실행
[ ] 새 draft는 새 Artifact
[ ] 변경된 draft 재검토
[ ] 새 Revision 생성
```

---

# STEP 5 — FastAPI Service Boundary

## Goal

Local UI/Discord/Notion이 Core/Graph를 직접 건드리지 않도록 FastAPI service boundary를 만든다.

## API Concept

```text
/agents
/workflows
/sessions
/sessions/{id}
/sessions/{id}/messages
/runs
/runs/{id}
/runs/{id}/resume
/runs/{id}/cancel
```

Follow-up message endpoint는 multipart 또는 동등한 방식으로 Message + Attachment를 함께 처리할 수 있어야 한다.

## Boundary

```text
- Workflow logic를 FastAPI endpoint에 직접 작성하지 않음
- Run ID / Session ID 기반 제어
- API client disconnect가 실행 state를 소실시키지 않음
- Active Run 1개 정책 유지
```

## Checkpoint

```text
[ ] API로 Session/Run 생성
[ ] 상태 조회
[ ] interrupt resume
[ ] follow-up + attachment 제출
[ ] continuation Run 생성 확인
[ ] cancel 동작
[ ] API disconnect 후 상태 유지
```

---

# STEP 6 — Local UI

## Goal

React 기반 Local UI에서 Agent/Workflow/Session/Run/History/Settings를 조작한다.

## Required UX

```text
Agents
Workflows
Runs / Sessions
History
Settings
```

Manager 결과 이후에도 입력창을 유지한다.

```text
Manager Result
[Follow-up 입력........................]
[파일 첨부]
[보내기]
```

## Boundary

```text
- UI 안에서 Workflow 직접 실행 금지
- 모든 상태 변경은 API 사용
- refresh/브라우저 재오픈 시 Run 상태 유지
- Visual Node Editor는 후속
```

## Checkpoint

```text
[ ] Agent/Workflow CRUD
[ ] Session/Run 실행 화면
[ ] 진행 상태 표시
[ ] WAITING_FOR_USER 입력
[ ] Manager 결과 이후 Follow-up 입력 유지
[ ] 여러 파일 첨부
[ ] Revision/History 표시
[ ] 브라우저 닫고 재접속 후 동일 상태
```

---

# STEP 7 — Discord Integration

## Goal

Discord를 원격 Interaction Interface로 사용한다.

## Scope

```text
Workflow 시작
상태 조회
Agent 질문 답변
Resume
Manager 결과 이후 Follow-up
결과 수신
Discord Attachment → Follow-up Attachment
```

Agent/Workflow 설정 편집은 Local UI에서만 한다.

## Boundary

```text
- Discord bot은 adapter 역할만
- FastAPI/Core service 사용
- Discord Thread/Channel ↔ WorkflowSession ID mapping
- allowlist 적용
- 긴 결과는 요약 + 파일/참조 방식 허용
```

## Checkpoint

```text
[ ] Discord start
[ ] status
[ ] HITL reply
[ ] resume
[ ] post-result follow-up
[ ] attachment ingest
[ ] final result 수신
```

---

# STEP 8 — Notion Interaction

## Goal

기존 Notion read-only 참고자료 기능을 유지하고 Workflow Inbox + Final Output write를 추가한다.

## Scope

```text
1. Agent 참고자료 Source
2. Ready 상태 기반 Workflow Inbox
3. Final Output 저장
```

초기에는 local polling을 사용한다.

## Safety

```text
생성 / append / 지정영역 update = 기본 허용
삭제 / 대규모 overwrite = 사용자 명시 승인 필요
```

## Checkpoint

```text
[ ] Notion source retrieval 유지
[ ] Ready task 감지
[ ] Run 생성
[ ] 완료 결과 write
[ ] Done 상태 반영
[ ] destructive write approval 정책 동작
[ ] Token이 DB/Git/log에 노출되지 않음
```

---

# STEP 9 — Desktop / Migration / Final QA

## Goal

Agent Workflow Studio 2.0을 안정적인 로컬 제품 형태로 마무리한다.

## Scope

- Tauri packaging 검토/적용
- startup/shutdown
- SQLite backup
- log rotation
- source/attachment cleanup policy
- legacy Workspace import UX
- recovery test
- regression test

## Final Acceptance Scenario

```text
1. Local Studio 실행
2. Agent/Workflow 확인
3. Career Workflow Session 생성
4. 최초 Run + 파일 첨부
5. 일부 Worker 완료
6. 프로세스 강제 종료
7. 다시 실행
8. 완료 Artifact/Run 복구
9. Manual Resume
10. Agent-requested HITL
11. 사용자 답변 후 same Run resume
12. Manager 결과 / Revision 생성
13. 사용자 Follow-up + 새 파일
14. Continuation Run 생성
15. 필요한 Worker만 재실행
16. 새 Artifact/Revision 생성
17. Discord에서 추가 Follow-up 수행
18. Notion에 Final 저장
19. History에서 Session/Run/Revision/Attachment 전체 추적
```

## Final Gate

위 시나리오와 단계별 regression test가 모두 PASS해야 2.0 완료로 판정한다.

---

# 5. 공통 GCB Template

향후 STEP마다 아래 형식으로 Issue/작업 지시를 생성한다.

```text
Goal
- STEP N의 목표를 구현한다.

Context
- 이전 STEP은 PASS 상태다.
- docs/PRD.md APPROVED v1.0을 제품 요구사항 Source of Truth로 사용한다.
- docs/migration_spec.md의 기존 기능을 임의로 잃지 않는다.
- 이 Roadmap의 STEP N 범위와 Checkpoint를 따른다.

Boundary
- 다음 STEP 기능을 미리 구현하지 않는다.
- 기존 app.py는 Migration 완료 전 frozen reference로 유지한다.
- 기존 기능을 근거 없이 삭제하지 않는다.
- WorkflowSession / Run / Message / Attachment / Artifact / Revision 경계를 유지한다.
- Agent-requested HITL = same Run Resume.
- Post-result Follow-up = same Session + Continuation Run.
- Follow-up Attachment = Turn-scoped default, permanent RAG 자동 승격 금지.
- 기존 Artifact / Revision overwrite 금지.
- Secret 저장 금지.
- 테스트하지 못한 항목은 PASS 처리하지 않는다.

Verification
- compile/static check
- 가능한 unit/integration test
- 변경 파일과 이유 요약
- Checkpoint 항목별 PASS/PARTIAL/FAIL 근거 기록

Gate
- Checkpoint 전부 PASS 전에는 다음 STEP으로 이동하지 않는다.
```

---

# 6. 운영 방식

각 단계는 아래 사이클로 진행한다.

```text
분석
→ 설계
→ 코드 작성
→ 테스트
→ Checkpoint 판정
→ GitHub PR
→ 사용자 확인/머지
→ 다음 STEP
```

각 STEP은 별도 branch와 Issue를 사용한다.

```text
main
├─ step1-core-engine
├─ step2-sqlite
├─ step3-langgraph
├─ step4-career-workflow
├─ step5-fastapi
├─ step6-local-ui
├─ step7-discord
├─ step8-notion
└─ step9-desktop-qa
```

---

# 7. Current Status

```text
STEP 0 Migration Spec              PASS
PRD v1.0                           APPROVED / MERGED
Roadmap & GCB                      v1.1
Current Issue                      #3 STEP 1
Current Branch                     step1-core-engine
Current Gate                       STEP 1 implementation pending
```

다음 작업은 STEP 1 GCB와 GitHub Issue #3의 최신 Checkpoint를 기준으로 진행한다.
