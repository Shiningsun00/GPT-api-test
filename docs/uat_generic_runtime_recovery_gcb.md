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

UAT found that the API run path defaulted to / only accepted `career_cover_letter`, so an otherwise valid generic Hierarchical workflow such as Manager + 2 Workers was blocked by Career-specific W1–W6 validation. This correction track restores the generic-first architecture without deleting the Career policy.

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

### Gate
- [x] Generic Linear arbitrary Agents PASS.
- [x] Generic Hierarchical Manager + N Workers PASS, including N=2.
- [x] Arbitrary Agent names PASS.
- [x] Duplicate Agent / distinct WorkerSlot PASS.
- [x] Initial / follow-up files semantics preserved.
- [x] HITL same-Run Resume preserved.
- [x] Error Manual Resume preserved.
- [x] Completed result follow-up = Continuation Run preserved.
- [x] 102 Python tests + R2 smoke + existing smokes/final acceptance + React test/build PASS.
- [x] PRD compliance review = PASS.

## R3 — Runtime Router / FastAPI — PASS
### Goal
Route each Run through the runtime selected by the durable Workflow policy rather than hard-wiring Career.

### Implemented behavior
- FastAPI resolves execution policy from persisted `Workflow.policy_id`; Generic (`None`) and `career_cover_letter` select different runtimes.
- `RunPayload.policy` is no longer a Career default. When supplied only as a compatibility hint, it cannot override the stored Workflow policy; mismatch returns 409.
- `/runs/with-files` follows the same stored-policy rule and supports Generic initial execution files rather than forcing Career.
- `/runs/{id}`, history, Resume, and Session follow-up resolve the runtime from the persisted Run/Workflow relationship.
- Follow-up validates that `previous_run_id` belongs to the same Workflow Session before starting a Continuation Run.
- Career runtime now resolves W1–W6 exclusively from `Workflow.policy_config.slot_roles[worker_id]`; Agent names are not role identifiers.
- Career execution-file target matching includes the explicit WorkerSlot binding while preserving stage/role/Agent targets.
- Generic and Career runtime/configuration errors are normalized with policy-specific error context.
- Existing STEP 9 initial-file API and fixtures were migrated to explicit Career policy semantics; Generic remains the default when no policy is selected.

### Gate
- [x] Run start resolves Workflow policy.
- [x] Generic Workflow → Generic runtime.
- [x] Career Workflow → Career runtime.
- [x] Career runtime consumes explicit WorkerSlot role bindings; no Agent-name role inference.
- [x] Generic Manager + 2 arbitrary Worker API E2E PASS.
- [x] Generic `/runs/with-files` resolves stored policy and passes execution-file evidence.
- [x] Generic Resume resolves runtime from the Run's Workflow and resumes the same Run/thread.
- [x] Generic completed-result Follow-up + file routes through Generic runtime and creates a Continuation Run + Revision v2.
- [x] Career API regression PASS with arbitrary Agent names + explicit slot roles.
- [x] Client policy override is rejected for JSON and multipart Run start paths.
- [x] Policy-specific validation/error separation PASS.
- [x] 108 Python unit/boundary tests PASS.
- [x] STEP 3, R2 Generic, STEP 4 Career, STEP 5 API, STEP 7 Discord, STEP 8 Notion, STEP 9 maintenance smokes PASS.
- [x] Final Acceptance 1–19 PASS.
- [x] React UI tests/build PASS.
- [x] PRD compliance review = PASS.

### R3 PRD compliance review
R3 restores the FastAPI service boundary required by FR-14 without coupling Generic execution to the Career template. Generic Linear/Hierarchical behavior remains the default capability; Career W1–W6 remains an explicit domain policy. Session/Run, same-Run HITL Resume, Continuation Run follow-up, file durability, immutable Artifact/Revision, and manual-recovery invariants remain intact. No new Product Decision outside approved PRD v1.0 was introduced.

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
**R0 PASS → R1 PASS → R2 PASS → R3 PASS → STOP. R4 implementation requires the next explicit user approval.**
