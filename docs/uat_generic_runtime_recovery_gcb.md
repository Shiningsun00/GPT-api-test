# Agent Workflow Studio 2.0 — Generic Runtime Recovery GCB

Status: ACTIVE UAT CORRECTION TRACK

## Source of Truth
1. `docs/PRD.md` — APPROVED v1.0 (highest priority)
2. `docs/migration_spec.md`
3. `docs/Agent_Workflow_Studio_2.0_Roadmap_GCB.md`
4. merged STEP 0–9 implementation
5. UAT findings / correction issue

If any implementation choice conflicts with the PRD, the PRD wins. A checkpoint cannot be marked PASS until the PRD compliance check passes.

## Problem Statement
The product is defined as a general-purpose, local-first Multi-Agent Workflow Studio. Domain-specific workflows such as the Career Cover Letter W1–W6 flow must live in a Workflow Policy / Template layer rather than being hard-wired into the generic execution path.

Current UAT found that the API run path defaults to / only accepts `career_cover_letter`, so an otherwise valid generic Hierarchical workflow such as Manager + 2 Workers is blocked by Career-specific W1–W6 validation. This correction track restores the generic-first architecture without deleting the Career policy.

## Cross-cutting PRD invariants
These are re-checked at every checkpoint:
- Generic Core / generic execution must not depend on Career W1–W6 naming or rules.
- Agent identity/name must remain reusable across workflows; domain roles belong to Workflow Policy / Template configuration, not the Agent name.
- WorkflowSession != Run.
- Agent-requested HITL resumes the same active Run/thread.
- Post-result user follow-up creates a new Continuation Run in the same Session.
- Follow-up attachments remain turn-scoped by default and are not automatically promoted to permanent RAG.
- Artifact / Revision history stays append-only.
- Restart never auto-resumes OpenAI/API work; Manual Resume remains required.
- Single-user / Local-first remains the 2.0 operating model.
- Secrets stay out of ordinary SQLite domain data, checkpoints, export/import, Git, and logs.
- Career Cover Letter remains a policy/template; it must not be removed to make Generic work.

---

# Multi-turn Recovery Plan

## R0 — Gap Freeze / Architecture Decision — PASS
### Goal
Freeze the exact PRD mismatch and decide the smallest correction architecture before implementation.

### Approved decisions
- `Workflow.policy_id=None` = Generic; `career_cover_letter` is explicit.
- Policy-specific role binding lives at Workflow/WorkerSlot level, not Agent name.
- Existing Workflows remain Generic by default; Career upgrade is conservative and evidence-based.
- Generic Linear follows saved Step order/additional prompts.
- Generic Hierarchical uses a durable Manager loop that may delegate WorkerSlot(s), request Human Input, or return Final.

### Gate
- [x] Career hard-wiring points mapped.
- [x] Workflow policy/template storage decided.
- [x] Agent-name-independent role binding decided.
- [x] Generic Linear semantics decided.
- [x] Generic Hierarchical semantics decided.
- [x] Backward compatibility behavior decided.
- [x] PRD compliance review = PASS.

## R1 — Domain / Persistence Policy Separation — PASS
### Goal
Represent Generic vs domain Policy/Template explicitly in durable Workflow configuration.

### Gate
- [x] Durable Workflow policy/template representation.
- [x] Generic default for new Workflows.
- [x] Policy-specific role bindings at Workflow/slot level.
- [x] SQLite v1→v2 migration is versioned/idempotent/reopen-safe.
- [x] Conservative Career compatibility upgrader.
- [x] Secret-like policy config rejected.
- [x] 95 Python tests + existing smokes/final acceptance + React test/build PASS.
- [x] PRD compliance review = PASS.

## R2 — Generic Runtime — PASS
### Goal
Allow arbitrary user-defined Linear and Hierarchical workflows to execute without Career W1–W6 requirements.

### Implemented behavior
- `GenericWorkflowRuntime` runs only Generic (`policy_id=None`) Workflows and never infers behavior from Agent names.
- Generic Linear executes arbitrary ordered Agents using saved Step IDs/additional prompts and persists immutable Artifacts + Revision.
- Generic Hierarchical uses LangGraph Manager → WorkerSlot(s) / Human Input / Final routing.
- WorkerSlot ID is the routing identity; the same Agent may occupy multiple distinct WorkerSlots.
- Manager/Worker artifacts are passed as data context, never promoted to system instructions.
- Initial execution-file routing and turn-scoped follow-up attachments are preserved.
- Manager-requested HITL resumes the same Run/thread.
- Worker failure pauses the Run; Manual Resume continues from the failed node without replaying the completed Manager decision.
- Completed-result follow-up is durably saved first, creates a new Continuation Run, and appends Revision vN+1.
- R2 does not alter FastAPI/UI runtime selection; those are intentionally gated to R3/R4.

### Gate
- [x] Generic Linear runtime works for arbitrary ordered Agents.
- [x] Generic Hierarchical runtime works for Manager + N Workers, including N=2.
- [x] Agent names are unrestricted in Generic runtime.
- [x] Duplicate Agent in distinct WorkerSlots remains valid.
- [x] Initial files and turn-scoped follow-up files are available according to routing semantics.
- [x] HITL same-Run Resume remains valid.
- [x] Error Manual Resume remains valid without replaying completed Manager work.
- [x] Post-result follow-up creates a Continuation Run and new Revision.
- [x] 102 Python tests PASS.
- [x] R2 Generic runtime smoke PASS: Manager + arbitrary Worker 2명 Hierarchical; arbitrary Agent 2명 Linear.
- [x] Existing STEP 3/4/5/7/8/9 smokes + Final Acceptance 1–19 PASS.
- [x] React test/build PASS.
- [x] PRD compliance review = PASS for R2 scope.

### Compliance note
The Recovery track is not complete. The service boundary still hard-wires Career runtime and the legacy Career runtime still resolves W1–W6 from Agent names. These known violations are explicitly reserved for R3 and are not accepted as final behavior.

## R3 — Runtime Router / FastAPI — PENDING
### Goal
Route a Run to the Workflow's selected policy/runtime rather than hard-wiring Career.

### Required
- Run start resolves policy from Workflow configuration.
- Generic Workflow invokes Generic runtime.
- Career Workflow invokes Career runtime.
- Career runtime consumes explicit WorkerSlot role bindings rather than Agent-name prefixes.
- Generic Manager + 2 Worker API E2E PASS.
- Career API regression PASS using explicit policy/role binding.
- Resume/follow-up routing selects the correct runtime for the Run's Workflow.
- Error responses distinguish invalid generic structure from policy-specific validation.
- PRD compliance review = PASS.

## R4 — Local UI / Template UX — PENDING
### Goal
Make the generic-first model obvious and prevent the UI from implying Career-specific naming rules for normal Agents.

### Required
- Workflow form exposes Generic vs Career policy/template selection.
- Generic is the default.
- Agent name examples are domain-neutral.
- Career role mapping UI appears only for Career policy.
- Career missing/duplicate roles are pre-validated.
- Manager + 2 Worker Generic Workflow can be created/started from UI.
- Issue #21 API-base connection UX is fixed/regression-tested.
- UI tests/build PASS.
- PRD compliance review = PASS.

## R5 — Regression / UAT Gate — PENDING
### Goal
Prove that restoring Generic execution did not break Career or cross-cutting durability guarantees.

### Required
- Generic Hierarchical + Linear E2E.
- No W1–W6 name dependency in Generic.
- Duplicate Agent/distinct WorkerSlots.
- Career explicit policy/role binding regression.
- Initial file, HITL, Manual Resume, Continuation Run, immutable Artifact/Revision.
- Discord/Notion policy-aware regressions.
- Backup/import/recovery regression.
- React tests/build.
- Final UAT and PRD compliance review.

## Merge rule
No implementation PR is merged until R0–R5 relevant gates are checked and the final PRD compliance review is PASS. If a checkpoint exposes a new product decision not fixed by PRD v1.0, stop and ask the user before implementing that decision.

## Current gate
**R0 PASS → R1 PASS → R2 PASS → STOP. User approval required before R3 implementation.**
