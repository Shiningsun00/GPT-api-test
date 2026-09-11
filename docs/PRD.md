# Agent Workflow Studio 2.0 — Product Requirements Document (PRD)

> 문서 상태: **APPROVED v1.0**  
> PRD 버전: **v1.0**  
> 승인일: **2026-09-11**  
> 기준 문서: `docs/migration_spec.md`  
> 기준 제품: 기존 Streamlit 기반 Agent Workflow Studio  
> 목표 제품: **Local-first 범용 Multi-Agent Workflow Studio**  
> 작성 목적: STEP 1 이후 구현 중 제품 방향이 흔들리지 않도록 제품 목표, 사용자 경험, 기능 범위, 안정성 기준, 보안 원칙과 완료 조건을 고정한다.

## v1.0 확정사항

- Manager가 결과를 제공한 뒤에도 동일 Workflow 대화를 계속할 수 있는 **사용자 주도 HITL Follow-up**을 MUST 요구사항으로 확정한다.
- Follow-up 명령과 함께 파일을 첨부할 수 있도록 한다.
- Agent가 질문해서 멈추는 `Interrupt → Resume`와 사용자가 결과를 본 뒤 추가 지시를 주는 `Post-result Follow-up`을 구분한다.
- 이미 완료된 실행을 다시 RUNNING으로 되돌리지 않도록 `Workflow Session/Thread`와 개별 `Run`의 개념을 구분한다.
- 초기 Run뿐 아니라 Follow-up 메시지에도 Run-only 파일을 연결할 수 있도록 데이터 요구사항을 확장한다.
- D-01~D-10 Product Decision을 모두 승인한다.

---

# 1. Product Vision

Agent Workflow Studio 2.0은 사용자가 여러 LLM Agent를 생성하고, 각 Agent의 역할·참고자료·실행 순서를 조합하여 반복 가능한 Agent Workflow를 구성하고 실행할 수 있는 **로컬 우선(local-first) Agent Workflow 플랫폼**이다.

제품의 핵심은 단순한 챗봇 UI가 아니라 다음과 같은 장기 실행 Workflow의 안정적 운영이다.

```text
사용자 요청
   ↓
Manager / Router
   ↓
전문 Worker 실행
   ↓
Artifact 저장
   ↓
검토 / 재작업 / Human Input
   ↓
Checkpoint / Resume
   ↓
Manager 결과
   ↓
사용자 Follow-up + 선택적 파일 첨부
   ↓
필요 Worker 재실행 / 새 Artifact / 새 Revision
```

사용자는 로컬 UI에서 Agent와 Workflow를 만들고 관리하며, 이후 Discord 또는 Notion을 외부 Interaction Interface로 사용해 동일 Workflow Session을 시작하거나 이어갈 수 있다.

---

# 2. Product Positioning

## 2.1 무엇을 만드는가

**범용 Agent Workflow Studio**를 만든다.

자기소개서 작성, 기업 분석, 보고서 분석 등의 특정 업무는 Core Engine에 하드코딩하지 않고 **Workflow Policy / Template**로 구현한다.

```text
Agent Workflow Studio 2.0
├─ 범용 Workflow Engine
│
├─ Template: 자기소개서 작성
│  └─ W1 → W2 → W3 → W6 → W3 → W4 → W5/W6
│
├─ Template: 논문 분석
│  └─ Summary → Critic → Manager
│
└─ Template: 데이터 분석
   └─ Analyst → Reviewer → Manager
```

## 2.2 무엇이 아닌가

초기 2.0은 다음을 목표로 하지 않는다.

- 대규모 SaaS 서비스
- 불특정 다중 사용자용 공개 플랫폼
- Agent Marketplace
- 자체 LLM 학습 시스템
- 기업용 IAM / RBAC
- 클라우드 분산 Job Queue

---

# 3. Primary User

## Primary Persona

로컬 PC에서 자신의 업무·학습·취업 준비에 사용할 Agent Workflow를 직접 구성하는 개인 사용자.

핵심 요구:

- 코드를 매번 수정하지 않고 Agent를 만들고 싶다.
- Agent마다 System Prompt와 참고자료를 설정하고 싶다.
- 여러 Agent가 역할을 나누어 일하게 하고 싶다.
- 긴 Workflow가 중간에 멈춰도 처음부터 다시 돌리고 싶지 않다.
- Agent가 추가 정보가 필요하면 질문하고, 답변 후 같은 작업을 이어가길 원한다.
- Manager 결과를 확인한 뒤 사용자가 직접 수정·재검토 명령을 내리고 싶다.
- 그 Follow-up 명령에 새로운 파일을 함께 첨부해 추가 근거로 사용하고 싶다.
- 실행 결과와 수정 이력을 남기고 싶다.
- 최종적으로 Discord나 Notion에서도 같은 Workflow와 상호작용하고 싶다.

---

# 4. Product Principles

## P1. Local First

중앙 서버 없이 개인 PC에서 Core Engine, DB, 파일 저장소를 운영할 수 있어야 한다.

## P2. Execution is independent from UI

UI가 닫히거나 새로고침되어도 Run 상태는 유지되어야 한다.

## P3. Resume, not Restart

오류·프로세스 종료·Human Input 발생 후 마지막 정상 Checkpoint에서 이어갈 수 있어야 한다.

## P4. Generic Core, Domain Policies

자기소개서 W1~W6와 같은 업무 규칙은 범용 Workflow Engine과 분리한다.

## P5. Artifact as Evidence

Worker 결과는 Artifact로 저장되고, 수정 시 기존 Artifact를 덮어쓰지 않는다.

## P6. Human Control

사용자는 Agent가 질문했을 때 답하는 것뿐 아니라, Manager가 결과를 낸 이후에도 같은 Workflow Session에서 직접 추가 지시를 줄 수 있어야 한다.

## P7. Follow-up Files are Turn-scoped by Default

Follow-up에 첨부한 파일은 기본적으로 해당 사용자 Turn과 그 Turn에서 파생된 Worker 작업에만 사용한다. 사용자가 별도로 승격하지 않는 한 Agent의 영구 RAG Source로 자동 등록하지 않는다.

## P8. Secrets stay secret

OpenAI API Key, Notion Token, Discord Token은 Workspace export, SQLite 일반 데이터, 로그, Git에 평문 저장하지 않는다.

---

# 5. Target Architecture

```text
                        ┌──────────────┐
                        │ Local UI     │
                        │ React        │
                        └──────┬───────┘
                               │
Discord Bot ──────┐            │
                  ▼            ▼
             ┌──────────────────────┐
             │       FastAPI        │
             └──────────┬───────────┘
                        │
                   ┌────▼─────┐
                   │ LangGraph│
                   └────┬─────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
     Core Engine      SQLite       Retrieval
          │                           │
          ▼                           ├─ Local Files
        OpenAI                        └─ Notion
```

장기적으로 필요하면 Local UI를 Tauri로 패키징한다.

---

# 6. Core Concepts

## 6.1 Workflow

재사용 가능한 Agent 구성, Node/Worker 관계, Prompt와 Policy 정의다.

## 6.2 Workflow Session / Thread

하나의 지속적인 사용자–Manager 대화를 묶는 상위 단위다.

Manager가 한 번 Final 결과를 내더라도 사용자가 같은 맥락에서 Follow-up을 보내면 Session은 계속된다.

```text
Workflow Session S1
├─ Run R1 — 최초 요청 → Revision v1
├─ Run R2 — 사용자 Follow-up → Revision v2
└─ Run R3 — 사용자 Follow-up + 파일 → Revision v3
```

## 6.3 Run

하나의 실행 Turn을 의미한다.

- 최초 사용자 요청으로 시작할 수 있다.
- Agent Interrupt에 대한 답변은 같은 Active Run을 Resume한다.
- 이미 `COMPLETED`된 Run 이후 사용자의 새 Follow-up은 같은 Session 아래 **새 Continuation Run**으로 기록한다.

이 원칙으로 `COMPLETED → RUNNING` 같은 모호한 상태 역행을 피한다.

## 6.4 Artifact

Worker가 생성한 불변 산출물이다. 수정 시 새 Artifact를 생성한다.

## 6.5 Revision

사용자에게 보여준 Manager 결과 버전이다. Artifact와 별도 Entity다.

---

# 7. Core User Journeys

## Journey A — Agent 생성

```text
Agent 메뉴
→ 새 Agent
→ 이름
→ 모델
→ System Prompt
→ 참고자료 설정
→ 저장
```

Agent는 Workflow와 독립적으로 재사용 가능해야 한다.

## Journey B — Workflow 생성

```text
Workflow 생성
→ Linear / Hierarchical / Graph 선택
→ Agent/Worker 배치
→ 추가 Prompt 설정
→ 실행 정책 설정
→ 저장
```

## Journey C — Workflow 최초 실행

```text
Session 생성
→ 최초 Run 생성
→ 사용자 Prompt 입력
→ 실행 파일 첨부/라우팅
→ Workflow 시작
→ 단계별 Artifact 생성
→ 진행상태 확인
→ Manager 결과
→ Revision v1
```

## Journey D — Agent 요청형 Human-in-the-loop

Agent가 작업을 계속하기 위해 사용자의 정보가 필요한 경우다.

```text
Workflow 실행
→ Agent가 정보 부족 판단
→ Interrupt
→ Run = WAITING_FOR_USER
→ 사용자 질문 표시
→ 사용자 답변
→ 같은 Run Resume
→ 다음 단계 진행
```

이 경우는 **같은 Active Run을 Resume**한다.

## Journey E — Manager 결과 이후 사용자 주도 HITL Follow-up + 파일 첨부

Manager 결과를 받은 뒤 사용자가 직접 추가 명령을 내리는 경우다.

```text
Manager 결과 / Revision vN
→ 사용자 Follow-up 입력
→ 선택적으로 파일 1개 이상 첨부
→ Follow-up 메시지와 파일을 로컬에 먼저 저장
→ 같은 Workflow Session 아래 Continuation Run 생성
→ Manager가 기존 Revision + 새 명령 + 새 파일을 확인
→ Manager가 직접 처리 또는 필요한 Worker에 재작업 위임
→ Worker는 해당 Follow-up에 필요한 첨부파일을 전달받음
→ 새 Artifact 생성
→ Manager 최종 검토
→ Revision vN+1 생성
→ Session 유지
```

예:

```text
Manager:
LG엔솔 자기소개서 Revision v2를 완성했습니다.

User:
Q3는 이 실험 결과 기준으로 다시 수정해줘.
[GOAT_test_result.xlsx 첨부]

Manager:
파일을 이번 Follow-up 근거로 등록
→ 필요한 W1/W4/W5 재실행
→ Revision v3 생성
```

### Follow-up Attachment 원칙

- PDF, DOCX, PPTX, XLSX, CSV, TXT, MD 등 기존 지원 형식을 사용할 수 있어야 한다.
- 여러 파일을 한 Follow-up에 첨부할 수 있어야 한다.
- 파일은 LLM 호출 전에 로컬 저장소와 DB reference에 기록해야 한다.
- Follow-up 파일은 해당 Turn의 `Message`와 연결한다.
- 기본적으로 영구 Agent RAG에는 추가하지 않는다.
- Manager가 재작업을 위임하면 해당 Turn에서 필요한 Worker가 파일 내용을 사용할 수 있어야 한다.
- 이전 Revision과 과거 Artifact를 덮어쓰지 않는다.
- 파일 parsing에 실패하면 일부 내용을 조용히 누락한 채 실행하지 않고 사용자에게 오류를 표시한다.
- 앱이 종료되어도 아직 처리 중인 Follow-up과 첨부파일 reference를 복구할 수 있어야 한다.

## Journey F — 장애 복구

```text
Workflow 진행
→ PC/프로그램 종료
→ 재실행
→ 기존 Session/Run 발견
→ 마지막 Checkpoint 표시
→ 사용자가 Resume
```

## Journey G — Discord Interaction

```text
Discord 메시지/명령
→ FastAPI
→ 새 Session/Run 또는 기존 Session 연결
→ Workflow 실행
→ 질문 발생
→ Discord 답변
→ 기존 Run Resume
```

2.1에서는 Discord Follow-up 메시지에 첨부된 파일도 Local UI와 동일한 Turn-scoped Attachment 모델에 연결하는 것을 목표로 한다.

## Journey H — Notion Interaction

```text
Notion DB/Page
→ Agent 참고자료 읽기

또는

Notion 작업 상태 = Ready
→ Local Service 감지
→ Run 생성
→ Workflow 결과
→ 지정 Notion Page 업데이트
→ Done
```

---

# 8. Functional Requirements

## FR-01 Agent Management — MUST

사용자는 Agent를 생성, 수정, 삭제, 복제할 수 있어야 한다.

Agent 필수 속성:

```text
id
name
model
system_prompt
retrieval configuration
source references
created_at
updated_at
```

### Acceptance Criteria

- Agent 저장 후 프로그램 재실행 시 존재한다.
- Agent 변경이 기존 완료 Run의 과거 결과를 소급 변경하지 않는다.
- 같은 Agent를 여러 Workflow 또는 여러 Worker slot에서 재사용할 수 있다.

---

## FR-02 Reference Sources / RAG — MUST

지원 파일:

```text
PDF
DOCX
PPTX
XLSX
CSV
TXT
MD
```

기능:

- 파일 업로드
- SHA-256 기반 식별
- 텍스트 추출
- chunk 생성
- embedding
- Top-K retrieval
- 출처 metadata 유지
- Agent와 source 연결/해제

원본 파일 bytes를 Agent JSON에 직접 저장하지 않고 local source storage에서 관리한다.

---

## FR-03 Notion Read — MUST

Agent가 사용자가 지정한 Notion Page / Database를 참고자료로 사용할 수 있어야 한다.

- Source ID/URL만 Agent configuration에 저장
- Token은 Secret Provider에서 읽음
- fetch된 content는 cache로 취급
- Notion 연결 실패가 전체 DB를 손상시키지 않음

---

## FR-04 Linear Workflow — MUST

```text
Agent A
 ↓ output
Agent B
 ↓ output
Agent C
```

지원 기능:

- Agent 순서
- Step별 additional prompt
- 최초 Prompt 전달 옵션
- 실행 파일 target routing
- 단계별 결과 기록

---

## FR-05 Hierarchical / Graph Workflow — MUST

Manager가 현재 Run State와 완료 Artifact를 바탕으로 다음 Worker를 선택하거나 Final/Interrupt를 판단할 수 있어야 한다.

```text
Manager
  ↓
Router
  ├─ Worker A
  ├─ Worker B
  ├─ Human Input
  └─ Final
```

### Requirement

- 완료되지 않은 Artifact dependency 참조 금지
- Worker output을 system instruction으로 승격하지 않음
- 같은 작업의 불필요한 반복 방지
- 모든 decision을 추적 가능하게 기록

---

## FR-06 Artifact Model — MUST

각 주요 Worker output은 Artifact로 저장한다.

```text
Artifact
├─ id
├─ session_id
├─ run_id
├─ kind
├─ producer
├─ body
├─ dependencies
├─ metadata
├─ created_at
└─ sequence/display number
```

Artifact body는 생성 후 immutable하게 취급한다.

---

## FR-07 Revision — MUST

사용자에게 보여준 Manager 결과 버전을 Revision으로 관리한다.

Artifact와 Revision은 별도 Entity다.

```text
Revision v1
Revision v2
Revision v3
```

각 Revision에는 최소 다음을 기록한다.

- session_id
- source run_id
- user feedback / command
- final output
- 사용된 Artifact reference
- 사용된 Follow-up Attachment reference
- 생성 시간

---

## FR-08 Persistent Session / Run — MUST

Workflow Session과 개별 Run 상태를 SQLite에 영구 저장한다.

Run status 후보:

```text
CREATED
RUNNING
WAITING_FOR_USER
PAUSED
FAILED
CANCELLED
COMPLETED
```

프로그램 재시작 후에도 Session, Run 목록과 마지막 상태를 복구해야 한다.

Terminal Run 이후 사용자의 추가 명령은 같은 Session의 새로운 Continuation Run으로 생성한다.

---

## FR-09 Checkpoint / Resume — MUST

LangGraph persistent checkpoint를 사용하여 Active Run을 재개할 수 있어야 한다.

### 반드시 지원할 시나리오

```text
정상 실행
Worker 오류 후 Resume
프로세스 종료 후 Resume
Human Interrupt 후 Resume
사용자 답변 후 Resume
```

완료된 Worker가 이유 없이 다시 실행되면 안 된다.

---

## FR-10 Human-in-the-loop — MUST

HITL은 두 가지 유형을 모두 지원한다.

### A. Agent-requested HITL

Agent가 사용자만 확인할 수 있는 정보가 필요하면 Workflow를 실패시키는 대신 Interrupt한다.

```text
RUNNING
→ WAITING_FOR_USER
→ User answer
→ 같은 Run Resume
```

### B. User-initiated Post-result HITL

Manager가 결과를 제공한 뒤에도 사용자는 같은 Workflow Session에 새 명령을 보낼 수 있다.

```text
Revision vN
→ User follow-up
→ Continuation Run
→ Manager/Workers
→ Revision vN+1
```

Follow-up에는 파일 첨부를 허용한다.

---

## FR-11 Execution & Follow-up Files — MUST

파일은 최초 실행뿐 아니라 Manager 결과 이후의 Follow-up에도 첨부할 수 있어야 한다.

### Initial Run Files

```text
User Prompt
+ File(s)
→ 선택한 Agent/Worker target으로 routing
```

### Follow-up Files

```text
User Follow-up Message
+ File(s)
→ Message에 attachment 연결
→ Manager가 Follow-up context로 확인
→ 필요한 Worker에 해당 Turn의 파일 전달
```

### Acceptance Criteria

- 여러 파일 첨부 가능
- 지원 파일 형식은 기존 RAG 형식과 동일
- 첨부파일 이름, SHA-256, 크기, local storage path/reference 기록
- 첨부파일과 Message/Run 관계 저장
- 어떤 Worker가 어떤 파일을 전달받았는지 추적 가능
- Run-only 파일과 permanent Agent RAG Source를 구분
- Follow-up 파일을 자동으로 permanent source로 승격하지 않음
- parsing 실패 시 사용자에게 명확한 오류 표시
- crash/restart 후 attachment reference 복구 가능

---

## FR-12 Execution History — MUST

각 Workflow Session/Run에서 다음 정보를 조회할 수 있어야 한다.

```text
사용자 요청
Follow-up 메시지
Follow-up 첨부파일
현재 상태
실행된 Agent
생성 Artifact
Revision
Human messages
오류
재시도
Token usage
시작/종료 시간
```

Hidden chain-of-thought를 저장/노출하는 기능은 요구하지 않는다.

---

## FR-13 Workspace v1–v4 Import — MUST

기존 `agent_workspace.zip`을 2.0에서 import할 수 있어야 한다.

가져올 대상:

- Agents
- RAG original files
- Notion source references
- Linear Workflow
- Hierarchical Workflow
- Manager prompts

과거 Workspace ZIP에 포함되지 않았던 과거 Run/Revision은 복원 대상이 아니다.

---

## FR-14 FastAPI — MUST

UI/Discord/Notion adapter는 Core/Graph를 직접 조작하지 않고 FastAPI service boundary를 사용한다.

최소 API 개념:

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

메시지 생성 API는 향후 Local UI와 Discord에서 동일한 Follow-up + Attachment 처리 경로를 사용할 수 있어야 한다.

---

## FR-15 Local UI — MUST

UI 최소 메뉴:

```text
Agents
Workflows
Runs / Sessions
History
Settings
```

실행 화면은 다음을 보여준다.

```text
Session 대화
Run 상태
현재 단계
완료 단계
Waiting 질문
Manager 결과
Follow-up 입력창
파일 첨부
Revision History
오류/Resume
```

Manager 결과가 나온 뒤에도 대화 입력창과 파일 첨부 기능이 유지되어야 한다.

---

## FR-16 Discord — SHOULD (STEP 7)

Discord에서 다음을 지원한다.

- 새 Workflow Session/Run 시작
- 상태 조회
- Agent 질문 답변
- 기존 Active Run Resume
- Manager 결과 이후 Follow-up
- 결과 수신
- 가능하면 Discord 메시지 첨부파일을 Follow-up Attachment로 처리

Discord Thread/Channel과 Workflow Session ID를 연결한다.

---

## FR-17 Notion Write / Inbox — SHOULD (STEP 8)

지정된 Notion Page/Database에 Workflow 결과를 기록할 수 있어야 한다.

초기 구현은 polling 방식으로 시작하고 webhook은 후속 확장으로 둔다.

---

# 9. Domain Policy: Career Cover Letter

자기소개서 Workflow는 첫 번째 reference policy/template로 유지한다.

```text
W1 Evidence Intake
    +
W2 Company/Job Analysis
    ↓
W3 Candidate Preparation
    ↓
W6 Independent Selection Review
    ↓
W3 Strategy
    ↓
W4 Draft
    ↓
┌─────────────────┐
W5 Fact Review    W6 Reader Review
└────────┬────────┘
         ↓
      Manager
         ↓
  Revise or Final
```

핵심 invariant:

- candidates는 intake + analysis 이후 생성
- selection review는 candidates만 받아 독립적으로 평가
- strategy는 candidates + selection review 이후
- draft는 strategy 이후
- review는 최신 draft만 대상으로 함
- writer self-review 금지
- 수정 draft는 새로운 Artifact
- 변경된 draft는 다시 review
- 정보가 부족하면 Human Interrupt
- Manager 결과 이후 사용자 Follow-up이 들어오면 기존 Revision을 보존하고 새 Continuation Run에서 필요한 Agent만 재실행
- Follow-up 첨부파일은 해당 수정 요청의 새로운 근거로 사용할 수 있음

이 정책은 `policies/career_cover_letter.py` 또는 동등한 Template 정의로 분리한다.

---

# 10. Data Requirements

SQLite는 최소 다음 domain data를 영구 저장한다.

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
checkpoints
execution_events
run_files
run_file_targets
external_thread_links
```

## 10.1 Session / Run Relation

```text
workflow_sessions
└─ runs (1:N)
   ├─ initial run
   ├─ interrupt/resume remains same active run
   └─ post-result follow-up creates continuation run
```

## 10.2 Message Attachment Relation

```text
messages
└─ message_attachments
   └─ stored_file/source reference
```

Follow-up 파일은 Message와 연결되며, 실행 시 필요한 Worker target relation을 별도로 기록할 수 있다.

## Source of Truth 원칙

- Agent config → DB
- Workflow config → DB
- Session/Run state → DB / LangGraph Checkpoint
- Worker 결과 → Artifact
- 사용자 결과 버전 → Revision
- 영구 원본 파일 → Local source storage
- Run/Follow-up 첨부파일 → Local run attachment storage + DB reference
- Token/API Key → Secret Provider

---

# 11. Non-Functional Requirements

## NFR-01 Reliability — P0

프로그램 종료나 UI 종료로 완료 Artifact, 사용자 Follow-up 또는 이미 저장된 첨부파일 reference가 소실되면 안 된다.

## NFR-02 Recoverability — P0

마지막 정상 Checkpoint부터 사용자가 Resume할 수 있어야 한다.

## NFR-03 Observability — P0

Run마다 다음을 확인할 수 있어야 한다.

```text
현재 stage
최근 checkpoint
최근 Agent
현재 Session/Run ID
사용된 follow-up attachment
오류 type
오류 message
재시도 횟수
API request duration
Token usage (가능한 경우)
```

## NFR-04 Security — P0

Secret 금지 위치:

```text
Git repository
SQLite 일반 테이블
Workspace ZIP
Run JSON export
execution log
Artifact body metadata
```

## NFR-05 Deterministic State Transition — P0

같은 Checkpoint를 Resume할 때 완료된 Node가 이유 없이 다시 실행되지 않아야 한다.

완료 Run 이후 Follow-up은 새 Continuation Run으로 기록하여 기존 terminal state를 변경하지 않는다.

## NFR-06 Local Performance — P1

개인 PC 환경에서 실행 가능한 수준을 목표로 하며 대규모 동시 사용자 부하는 초기 요구사항이 아니다.

## NFR-07 Testability — P0

Core는 UI 없이 unit test가 가능해야 한다.

STEP 1 이후 Core package 내부에 `streamlit` import가 존재하면 안 된다.

## NFR-08 Attachment Durability — P0

사용자가 Follow-up을 제출한 뒤 LLM 실행이 시작되기 전에 첨부파일이 안정적인 로컬 저장소에 기록되어야 한다.

프로세스 종료 후에도 동일 Follow-up을 복구할 수 있어야 한다.

---

# 12. Error Handling Requirements

오류는 최소 다음 범주로 분류한다.

```text
Configuration
Authentication
Rate Limit / Quota
Timeout
Network
Context / Input Size
Invalid Model Output
Workflow Validation
Retrieval
File Parsing
External Integration
Persistence
Unknown Runtime
```

오류 발생 시 가능한 경우:

```text
FAILED가 아니라 PAUSED
→ 오류 정보 저장
→ 마지막 checkpoint 표시
→ Retry/Resume 제공
```

단, 복구 불가능한 validation/config 오류는 명확히 FAILED 처리할 수 있다.

Follow-up 파일 중 하나라도 필수 parsing에 실패하면 일부 파일만 조용히 누락해서 실행하지 않는다.

---

# 13. Security & Privacy

## 기본 정책

- 모든 Domain Data는 사용자 PC에 저장한다.
- 외부 전송은 사용자가 연결한 API Provider에 필요한 범위로 제한한다.
- 파일 원문이 어느 Agent에 전달되는지 추적 가능해야 한다.
- Follow-up 첨부파일은 해당 Turn의 근거로 취급하고 자동 영구 RAG 등록하지 않는다.
- Notion write는 지정한 destination으로 한정한다.
- Discord 연결은 허용 사용자/서버 범위를 설정할 수 있어야 한다.
- 삭제 기능은 DB record와 local source cleanup 정책을 명확히 분리한다.

---

# 14. Product Scope by Release

## 2.0 Core Release

STEP 0–5 완료 범위:

- Pure Python Core
- SQLite
- Workflow Session / Run model
- LangGraph
- Checkpoint / Resume / Interrupt
- Post-result HITL Follow-up
- Follow-up Attachment model
- Career workflow migration
- FastAPI

## 2.0 Local UI Release

STEP 6:

- React Local UI
- Agents
- Workflows
- Runs / Sessions
- History
- Settings
- Manager Follow-up chat
- Follow-up file attachment

## 2.1 Integration Release

STEP 7–8:

- Discord
- Discord follow-up / attachment mapping
- Notion write/inbox

## 2.2 Desktop Release

STEP 9:

- Tauri packaging 검토/적용
- Backup
- Migration UX
- Final regression QA

---

# 15. Out of Scope for Initial 2.0

다음 기능은 명시적인 범위 변경 전까지 구현하지 않는다.

- 공개 인터넷 SaaS hosting
- 다중 사용자 Account/Auth
- 팀 단위 RBAC
- 결제
- Agent Marketplace
- 수평 확장 Worker cluster
- Kubernetes
- Redis/Celery 기반 distributed queue
- 자체 vector database server
- Notion webhook 기반 실시간 sync
- 모바일 앱
- Follow-up 파일의 자동 영구 RAG 승격

---

# 16. Definition of Done

제품 2.0의 최종 acceptance scenario:

```text
1. PC에서 Agent Workflow Studio 실행
2. Agent/Workflow 확인
3. 자기소개서 Workflow Session 생성
4. 최초 Run 생성 + 파일 첨부
5. W1/W2/W3 등 일부 단계 실행
6. 프로그램 강제 종료
7. 프로그램 재실행
8. 기존 Session/Run과 완료 Artifact 확인
9. 마지막 Checkpoint부터 Resume
10. Human Input 필요 상태 진입
11. 사용자 답변 후 같은 Active Run Resume
12. Manager 결과 / Revision 생성
13. 사용자가 Manager 결과에 Follow-up 명령 입력
14. Follow-up에 새 파일 첨부
15. 같은 Session에서 Continuation Run 생성
16. Manager가 Follow-up + 파일을 바탕으로 필요한 Worker만 재실행
17. 새 Artifact와 새 Revision 생성
18. Discord에서 추가 Follow-up/Resume 수행
19. 최종 결과를 지정된 Notion Page에 저장
20. History에서 전체 Session/Run/Revision/Attachment 관계 확인
```

위 시나리오와 각 STEP별 regression test가 통과해야 완료로 본다.

---

# 17. 개발 운영 규칙

각 단계는 다음 흐름을 따른다.

```text
main
 ↓
stepN-* branch
 ↓
구현
 ↓
Tests
 ↓
Checkpoint PASS/PARTIAL/FAIL
 ↓
Pull Request
 ↓
사용자 확인
 ↓
Merge
 ↓
다음 STEP
```

### 원칙

- main 직접 개발 금지
- 다음 STEP 기능 선구현 금지
- 기존 `app.py`는 Migration 완료 전 frozen legacy reference
- Checkpoint FAIL이면 다음 STEP 진행 금지
- 테스트하지 못한 항목은 PASS 표시 금지
- 제품 방향 변경은 PRD Decision Log에 기록

---

# 18. Approved Product Decisions

## D-01 Primary Deployment Model — CONFIRMED

**결정:** `Single-user / Local-first`

Agent Workflow Studio 2.0의 첫 목표는 개인 PC 1대에서 사용하는 로컬 앱이다. 초기 범위에서 다중 사용자 인증, 중앙 DB와 클라우드 운영 복잡성은 제외한다.

---

## D-02 Provider Scope — CONFIRMED

**결정:** `OpenAI only in 2.0`, 단 Core interface는 provider 교체가 가능하도록 추상화한다.

초기 구현과 회귀 테스트는 OpenAI SDK를 기준으로 한다. Anthropic/Gemini 등은 후속 확장 시 adapter를 추가할 수 있도록 경계를 유지한다.

---

## D-03 Workflow UI Level — CONFIRMED

**결정:** `STEP 6은 안정적인 Form/List Editor 우선, Visual Node Editor는 후속 추가`

Core Engine과 저장 구조의 안정성을 먼저 확보하고, drag & drop Visual Graph Editor는 후속 UI 개선으로 다룬다.

---

## D-04 Concurrent Runs — CONFIRMED

**결정:** `초기 2.0은 한 번에 1개 Active Run`

다른 Run은 queue/paused 상태로 대기할 수 있다. 내부 Entity와 API는 추후 concurrent execution 확장이 가능하도록 설계한다.

---

## D-05 Restart Behavior — CONFIRMED

**결정:** `Manual Resume`

프로그램 재실행 시 중단 Run을 자동 실행하지 않는다. 사용자가 현재 상태와 마지막 Checkpoint를 확인한 뒤 Resume한다. 이를 통해 예기치 않은 API 비용과 외부 write를 방지한다.

---

## D-06 Legacy Workspace Compatibility — CONFIRMED

**결정:** `agent_workspace.zip Import only`

Workspace v1–v4는 2.0으로 import할 수 있어야 한다. 2.0의 DB/Graph 상태를 구버전 Workspace ZIP으로 다시 export하는 backward export는 지원하지 않는다.

---

## D-07 External Write Safety — CONFIRMED

**결정:**

```text
기본 = 생성/append 또는 지정 영역 update
삭제/대규모 overwrite = 사용자 명시 승인 필요
```

Discord Workflow 실행은 허용된 사용자/서버를 allowlist로 제한한다.

---

## D-08 Data Retention — CONFIRMED

**결정:** `사용자가 삭제하기 전까지 로컬에 보존`

Session, Run, Artifact, Revision, Message와 Follow-up Attachment 원본은 자동 삭제하지 않는다. 재생성 가능한 cache와 임시 추출물은 cleanup 대상으로 둘 수 있다.

---

## D-09 Discord Role — CONFIRMED

**결정:** Discord는 다음 Interaction을 지원한다.

```text
새 Workflow 시작
상태 조회
Agent 질문 답변
Active Run Resume
Manager 결과 이후 Follow-up
결과 수신
```

가능하면 Discord 첨부파일도 동일한 Follow-up Attachment 모델로 처리한다. Agent와 Workflow 설정 편집은 Local UI에서만 수행한다.

---

## D-10 Notion Role — CONFIRMED

**결정:** Notion은 다음 세 역할을 모두 지원한다.

```text
1. Agent 참고자료 Source
2. Ready 상태 기반 Workflow Inbox
3. Final Output 저장
```

초기 자동화는 polling 방식으로 구현하고 실시간 webhook은 후속 확장으로 둔다.

---

# 19. Confirmed Product Decision — Follow-up Attachment

## C-01 Manager Post-result HITL + File Attachment — CONFIRMED

```text
Manager가 결과를 제공한 후에도 사용자는 같은 Workflow Session에서 추가 명령을 보낼 수 있다.
Follow-up 메시지에는 파일을 함께 첨부할 수 있다.
첨부파일은 해당 Follow-up의 근거로 Manager 및 필요한 Worker에게 전달된다.
기존 Revision/Artifact는 보존하고 새 Continuation Run / Revision을 생성한다.
```

기본 routing 정책:

```text
User Follow-up + Attachment
→ Manager가 우선 해석
→ Manager가 직접 처리하거나 필요한 Worker 선택
→ 선택된 Worker에게 필요한 Follow-up Attachment 전달
```

사용자가 별도로 Agent/Worker target을 지정하는 고급 기능은 향후 UI 설계 시 추가할 수 있으나, 초기 MUST 요구사항은 **Manager 중심 자동 routing**이다.

---

# 20. Decision Log

| ID | Decision | Status |
|---|---|---|
| C-01 | Manager 결과 이후 Follow-up + 파일 첨부 | **Confirmed** |
| D-01 | Single-user / Local-first | **Confirmed** |
| D-02 | OpenAI only + provider abstraction | **Confirmed** |
| D-03 | Form/List UI first, Visual Editor later | **Confirmed** |
| D-04 | One Active Run initially | **Confirmed** |
| D-05 | Manual Resume after restart | **Confirmed** |
| D-06 | Legacy Workspace Import only | **Confirmed** |
| D-07 | Safe Notion write + destructive-action approval | **Confirmed** |
| D-08 | Retain until user deletion | **Confirmed** |
| D-09 | Full Discord interaction surface | **Confirmed** |
| D-10 | Notion source + inbox + output | **Confirmed** |

---

# 21. PRD Approval Gate

STEP 1 구현 전 Approval Gate:

```text
[x] D-01 ~ D-10 사용자 결정 완료
[x] C-01 Post-result HITL + File Attachment 요구사항 확정
[x] Product Vision 승인
[x] MUST / SHOULD 범위 승인
[x] Out of Scope 승인
[x] Definition of Done 승인
```

## Approval Result

```text
PRD STATUS = APPROVED v1.0
NEXT = STEP 1 — Pure Python Core Engine 분리
```

이 문서는 STEP 1 이후 제품 구현의 기준 문서다. 새로운 제품 방향이나 범위 변경이 발생하면 구현에 선행하여 Decision Log와 PRD version을 갱신한다.
