# Agent Workflow Studio 2.0 — Product Requirements Document (PRD)

> 문서 상태: **DRAFT — 사용자 결정 필요**  
> 기준 문서: `docs/migration_spec.md`  
> 기준 제품: 기존 Streamlit 기반 Agent Workflow Studio  
> 목표 제품: **Local-first 범용 Multi-Agent Workflow Studio**  
> 작성 목적: STEP 1 이후 구현 중 제품 방향이 흔들리지 않도록 제품 목표, 사용자 경험, 기능 범위, 안정성 기준, 보안 원칙과 완료 조건을 고정한다.

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
최종 결과
```

사용자는 로컬 UI에서 Agent와 Workflow를 만들고 관리하며, 이후 Discord 또는 Notion을 외부 Interaction Interface로 사용해 동일 Workflow를 시작하거나 이어갈 수 있다.

---

# 2. Product Positioning

## 2.1 무엇을 만드는가

**범용 Agent Workflow Studio**를 만든다.

자기소개서 작성, 기업 분석, 보고서 분석 등의 특정 업무는 Core Engine에 하드코딩하지 않고 **Workflow Policy / Template**로 구현한다.

예:

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

외부 시스템에 데이터를 쓰거나 중요한 Workflow를 재개할 때 사용자가 실행 상태와 결과를 확인할 수 있어야 한다.

## P7. Secrets stay secret

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

# 6. Core User Journeys

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

## Journey C — Workflow 실행

```text
Run 생성
→ 사용자 Prompt 입력
→ 실행 파일 첨부/라우팅
→ Workflow 시작
→ 단계별 Artifact 생성
→ 진행상태 확인
→ Final
```

## Journey D — Human in the Loop

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

## Journey E — 장애 복구

```text
Workflow 진행
→ PC/프로그램 종료
→ 재실행
→ 기존 Run 발견
→ 마지막 Checkpoint 표시
→ Resume
```

## Journey F — Discord Interaction

```text
Discord 메시지/명령
→ FastAPI
→ 새 Run 또는 기존 Run 연결
→ Workflow 실행
→ 질문 발생
→ Discord 답변
→ 기존 Run Resume
```

## Journey G — Notion Interaction

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

# 7. Functional Requirements

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

### Requirement

원본 파일 bytes를 Agent JSON에 직접 저장하지 않고 local source storage에서 관리한다.

---

## FR-03 Notion Read — MUST

Agent가 사용자가 지정한 Notion Page / Database를 참고자료로 사용할 수 있어야 한다.

### Requirement

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

사용자에게 보여준 결과 버전을 Revision으로 관리한다.

Artifact와 Revision은 별도 Entity다.

```text
Revision v1
Revision v2
Revision v3
```

각 Revision에는 최소 다음을 기록한다.

- user feedback
- final output
- 사용된 Artifact reference
- 생성 시간

---

## FR-08 Persistent Run — MUST

Run 상태를 SQLite에 영구 저장한다.

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

프로그램 재시작 후에도 Run 목록과 마지막 상태를 복구해야 한다.

---

## FR-09 Checkpoint / Resume — MUST

LangGraph persistent checkpoint를 사용하여 Workflow를 재개할 수 있어야 한다.

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

Agent가 사용자만 확인할 수 있는 정보가 필요하면 Workflow를 실패시키는 대신 Interrupt한다.

질문은 사용자가 이해할 수 있는 형태로 표시한다.

Resume 시 기존 Run ID와 Checkpoint를 사용한다.

---

## FR-11 Execution Files — MUST

Run을 시작할 때 파일을 첨부하고 하나 이상의 Worker/Agent target에 전달할 수 있어야 한다.

영구 Agent RAG Source와 Run-only Execution File은 구분한다.

---

## FR-12 Execution History — MUST

각 Run에서 다음 정보를 조회할 수 있어야 한다.

```text
사용자 요청
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
/runs
/runs/{id}
/runs/{id}/resume
/runs/{id}/cancel
/runs/{id}/messages
```

---

## FR-15 Local UI — MUST

UI 최소 메뉴:

```text
Agents
Workflows
Runs
History
Settings
```

실행 화면은 다음을 보여준다.

```text
Run 상태
현재 단계
완료 단계
Waiting 질문
최종 결과
Revision History
오류/Resume
```

---

## FR-16 Discord — SHOULD (STEP 7)

Discord에서 새 Run을 시작하거나 Human Input이 필요한 기존 Run에 답변할 수 있어야 한다.

Discord Thread/Channel과 Run ID 연결을 저장한다.

---

## FR-17 Notion Write / Inbox — SHOULD (STEP 8)

지정된 Notion Page/Database에 Workflow 결과를 기록할 수 있어야 한다.

초기 구현은 polling 방식으로 시작하고 webhook은 후속 확장으로 둔다.

---

# 8. Domain Policy: Career Cover Letter

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

이 정책은 `policies/career_cover_letter.py` 또는 동등한 Template 정의로 분리한다.

---

# 9. Data Requirements

SQLite는 최소 다음 domain data를 영구 저장한다.

```text
agents
sources
agent_sources
workflows
workflow_nodes / workflow_workers
runs
messages
artifacts
artifact_dependencies
revisions
checkpoints
execution_events
run_files
run_file_targets
external_thread_links
```

## Source of Truth 원칙

- Agent config → DB
- Workflow config → DB
- Run state → DB / LangGraph Checkpoint
- Worker 결과 → Artifact
- 사용자 결과 버전 → Revision
- 원본 파일 → Local source storage
- Token/API Key → Secret Provider

---

# 10. Non-Functional Requirements

## NFR-01 Reliability — P0

프로그램 종료나 UI 종료로 완료 Artifact가 소실되면 안 된다.

## NFR-02 Recoverability — P0

마지막 정상 Checkpoint부터 사용자가 Resume할 수 있어야 한다.

## NFR-03 Observability — P0

Run마다 다음을 확인할 수 있어야 한다.

```text
현재 stage
최근 checkpoint
최근 Agent
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

## NFR-06 Local Performance — P1

개인 PC 환경에서 실행 가능한 수준을 목표로 하며 대규모 동시 사용자 부하는 초기 요구사항이 아니다.

## NFR-07 Testability — P0

Core는 UI 없이 unit test가 가능해야 한다.

STEP 1 이후 Core package 내부에 `streamlit` import가 존재하면 안 된다.

---

# 11. Error Handling Requirements

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

---

# 12. Security & Privacy

## 기본 정책

- 모든 Domain Data는 사용자 PC에 저장한다.
- 외부 전송은 사용자가 연결한 API Provider에 필요한 범위로 제한한다.
- 파일 원문이 어느 Agent에 전달되는지 추적 가능해야 한다.
- Notion write는 지정한 destination으로 한정한다.
- Discord 연결은 허용 사용자/서버 범위를 설정할 수 있어야 한다.
- 삭제 기능은 DB record와 local source cleanup 정책을 명확히 분리한다.

---

# 13. Product Scope by Release

## 2.0 Core Release

STEP 0–5 완료 범위:

- Pure Python Core
- SQLite
- LangGraph
- Career workflow migration
- FastAPI

## 2.0 Local UI Release

STEP 6:

- React Local UI
- Agents
- Workflows
- Runs
- History
- Settings

## 2.1 Integration Release

STEP 7–8:

- Discord
- Notion write/inbox

## 2.2 Desktop Release

STEP 9:

- Tauri packaging 검토/적용
- Backup
- Migration UX
- Final regression QA

---

# 14. Out of Scope for Initial 2.0

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

---

# 15. Definition of Done

제품 2.0의 최종 acceptance scenario:

```text
1. PC에서 Agent Workflow Studio 실행
2. Agent/Workflow 확인
3. 자기소개서 Workflow Run 생성
4. W1/W2/W3 등 일부 단계 실행
5. 프로그램 강제 종료
6. 프로그램 재실행
7. 기존 Run과 완료 Artifact 확인
8. 마지막 Checkpoint부터 Resume
9. Human Input 필요 상태 진입
10. Discord에서 답변
11. 동일 Run Resume
12. Draft 생성
13. 두 Reviewer 검증
14. Final Revision 생성
15. 지정된 Notion Page에 결과 저장
16. History에서 전체 Run/Revision 확인
```

위 시나리오와 각 STEP별 regression test가 통과해야 완료로 본다.

---

# 16. 개발 운영 규칙

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

# 17. 사용자 확정 필요 — Product Decisions

아래 항목은 구현 방식에 큰 영향을 주므로 **STEP 1 본격 구현 전에 확정하는 것을 권장한다.**

## D-01 Primary Deployment Model

**질문:** 2.0의 첫 목표를 정말로 개인 PC 1대에서 사용하는 Single-user Local App으로 고정할 것인가?

**추천안:** `YES — Single-user / Local-first`

이 경우 다중 사용자 인증, 중앙 DB, 클라우드 배포 복잡성을 초기 범위에서 제외한다.

상태: **NEEDS USER CONFIRMATION**

---

## D-02 Provider Scope

**질문:** 초기 2.0에서 OpenAI API만 지원할 것인가, Anthropic/Gemini 등 Multi-provider까지 처음부터 지원할 것인가?

**추천안:** `OpenAI only in 2.0`, 단 Core interface는 provider 교체가 가능하도록 추상화.

이유: 현재 모든 기존 기능이 OpenAI SDK 기반이며, provider를 처음부터 늘리면 structured output, tool use, usage, error 처리 테스트 범위가 급격히 증가한다.

상태: **NEEDS USER CONFIRMATION**

---

## D-03 Workflow UI Level

**질문:** Local UI에서 처음부터 Node drag & drop 방식의 Visual Graph Editor가 필수인가?

선택지:

```text
A. STEP 6부터 Visual Node Editor 포함
B. STEP 6은 안정적인 Form/List Editor, Visual Graph는 후속 추가
```

**추천안:** `B`

먼저 Workflow Engine과 저장 구조를 안정화한 뒤 React Flow 등 Visual Editor를 추가하는 편이 안전하다.

상태: **NEEDS USER CONFIRMATION**

---

## D-04 Concurrent Runs

**질문:** 초기 버전에서 여러 Workflow를 동시에 실행해야 하는가?

선택지:

```text
A. 여러 Run 동시 실행
B. 한 번에 1개 active Run + 나머지는 queue/paused
```

**추천안:** `B` for initial 2.0

이유: 개인 PC + API rate limit 환경에서 안정성, Resume, 오류 추적이 훨씬 단순하다. 구조는 추후 concurrent execution이 가능하게 설계한다.

상태: **NEEDS USER CONFIRMATION**

---

## D-05 Restart Behavior

**질문:** 프로그램을 재실행했을 때 중단 Run을 자동으로 계속 실행할까, 사용자가 Resume 버튼을 눌러야 할까?

**추천안:** `Manual Resume`

재부팅 직후 예상치 못한 API 비용이나 외부 write가 발생하는 것을 막는다.

상태: **NEEDS USER CONFIRMATION**

---

## D-06 Legacy Workspace Compatibility

**질문:** 기존 `agent_workspace.zip`은 2.0으로 **import만** 지원하면 되는가, 2.0에서 다시 구버전 ZIP으로 export해야 하는가?

**추천안:** `Import only`

2.0의 DB/Graph 상태는 legacy schema로 표현할 수 없기 때문에 backward export는 복잡성과 데이터 손실 위험이 크다.

상태: **NEEDS USER CONFIRMATION**

---

## D-07 External Write Safety

**질문:** Notion에 결과를 쓸 때 Agent가 자동으로 기존 내용을 수정하도록 허용할 것인가?

**추천안:**

```text
기본 = 생성/append 또는 지정 영역 update
삭제/대규모 overwrite = 사용자 명시 승인 필요
```

Discord 역시 Workflow를 실행할 수 있는 서버/사용자를 allowlist로 제한한다.

상태: **NEEDS USER CONFIRMATION**

---

## D-08 Data Retention

**질문:** Run, Artifact, Revision, 메시지를 기본적으로 얼마나 보관할 것인가?

**추천안:** `사용자가 삭제하기 전까지 로컬에 보존`

캐시/임시 파일은 cleanup 가능하지만 Artifact/Revision은 audit와 Resume에 중요하므로 자동 삭제하지 않는다.

상태: **NEEDS USER CONFIRMATION**

---

## D-09 Discord Role

**질문:** Discord를 어느 수준의 UI로 사용할 것인가?

선택지:

```text
A. 새 Workflow 시작 + 질문 답변 + 상태 조회 + 결과 수신
B. Human Input/Resume 용도만
```

**추천안:** `A`

단 Agent/Workflow 설정 편집은 Local UI에서만 수행한다.

상태: **NEEDS USER CONFIRMATION**

---

## D-10 Notion Role

**질문:** Notion을 어느 수준으로 사용할 것인가?

추천 범위:

```text
1. Agent 참고자료 source
2. Ready 상태 기반 Workflow Inbox
3. Final output 저장
```

**추천안:** `1 + 2 + 3`

초기에는 polling, 실시간 webhook은 후속 범위.

상태: **NEEDS USER CONFIRMATION**

---

# 18. Decision Log

사용자 확정 후 아래 표를 갱신한다.

| ID | Decision | Status |
|---|---|---|
| D-01 | Primary Deployment Model | Pending |
| D-02 | Provider Scope | Pending |
| D-03 | Workflow UI Level | Pending |
| D-04 | Concurrent Runs | Pending |
| D-05 | Restart Behavior | Pending |
| D-06 | Legacy Workspace Compatibility | Pending |
| D-07 | External Write Safety | Pending |
| D-08 | Data Retention | Pending |
| D-09 | Discord Role | Pending |
| D-10 | Notion Role | Pending |

---

# 19. PRD Approval Gate

STEP 1 구현 전 다음 조건을 만족한다.

```text
[ ] D-01 ~ D-10 사용자 결정 완료
[ ] Product Vision 승인
[ ] MUST / SHOULD 범위 승인
[ ] Out of Scope 승인
[ ] Definition of Done 승인
```

모두 확정되면 문서 상태를:

```text
DRAFT
→ APPROVED v1.0
```

으로 변경하고 STEP 1을 시작한다.
