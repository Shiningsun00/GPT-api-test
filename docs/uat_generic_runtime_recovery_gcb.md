# Agent Workflow Studio 2.0 — Generic Runtime Recovery GCB

Status: R0–R5 PASS / AWAITING MERGE APPROVAL

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
- [x] Durable Workflow policy/template representation.
- [x] Generic default for new Workflows.
- [x] Policy-specific role bindings at Workflow/slot level.
- [x] SQLite v1→v2 migration is versioned/idempotent/reopen-safe.
- [x] Conservative Career compatibility upgrader.
- [x] Secret-like policy config rejected.
- [x] 95 Python tests + existing smokes/final acceptance + React test/build PASS.
- [x] PRD compliance review = PASS.

## R2 — Generic Runtime — PASS
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

## R4 — Local UI / Template UX — PASS
- [x] Workflow form exposes Generic vs Career policy/template selection.
- [x] Generic is the default.
- [x] Agent name examples are domain-neutral.
- [x] Career role mapping UI appears only for Career policy.
- [x] Career missing/duplicate roles are pre-validated.
- [x] Manager + 2 Worker Generic Workflow UI contract + backend execution path PASS.
- [x] Issue #21 API-base connection UX fixed and regression-tested.
- [x] 11 React/Vitest UI contract tests PASS.
- [x] Vite production build PASS.
- [x] 108 Python unit/boundary tests + STEP 3/R2/STEP 4/5/7/8/9 smokes + Final Acceptance 1–19 PASS.
- [x] PRD compliance review = PASS.

## R5 — Regression / UAT Merge Gate — PASS
### Final gate
- [x] Generic Hierarchical Manager + 2 arbitrary Workers → Final PASS.
- [x] Generic Linear 2+ arbitrary Agents → Final PASS.
- [x] Generic execution has no W1–W6 Agent-name dependency.
- [x] Duplicate Agent / distinct WorkerSlots regression PASS.
- [x] Career template regression PASS with explicit WorkerSlot W1–W6 binding and arbitrary Agent names.
- [x] Initial Run + execution file durability/routing PASS.
- [x] Agent-requested HITL → same Run/thread Resume PASS.
- [x] Worker failure → explicit Manual Resume without replaying completed work PASS.
- [x] Completed result → Follow-up + file → Continuation Run + new Revision PASS.
- [x] Restart/reopen leaves interrupted/paused Run waiting for explicit Resume; no automatic external/API work PASS.
- [x] Artifact / Revision append-only and historical immutability PASS.
- [x] Discord regression PASS (start/status/reply/resume/follow-up/attachment + allowlist/durable mapping coverage).
- [x] Notion regression PASS (source/inbox/final write, idempotency and non-destructive write policy coverage).
- [x] Backup / validate / import / restore / cleanup regression PASS.
- [x] Existing Final Acceptance 1–19 PASS.
- [x] Dedicated `manual_r5_recovery_acceptance.py` PASS.
- [x] 108 Python unit/boundary tests PASS.
- [x] UI/Vitest 11 tests PASS.
- [x] Vite production build PASS.
- [x] Latest branch-head GitHub Actions run `34667813793`: `unit-tests` SUCCESS, `local-ui` SUCCESS.
- [x] **R5 FINAL PRD compliance = PASS.**

### R5 PRD compliance review
The recovery branch was re-checked against approved PRD v1.0 Product Vision, P1–P8, FR-01/04/05/06/07/08/09/10/11/12/14/15, Career Policy invariants, NFR-01/02/04/05/07/08, D-01/03/04/05/06/07/08/09/10, and C-01. The correction restores the generic-first architecture rather than changing product scope: domain policy remains separated from Core, Agents remain reusable, local persistence/checkpoints remain authoritative, terminal Runs are not reactivated, follow-up files remain turn-scoped, and external integrations keep their existing safety boundaries. No new Product Decision outside PRD v1.0 was required by R5.

### R5 validation evidence
- GitHub Actions branch-head run `34667813793` includes an explicit `Run R5 recovery acceptance gate` step and it completed successfully.
- The R5 gate reruns the complete 108-test Python suite, Generic runtime smoke, and the established product acceptance/recovery/integration suites.
- The independent Local UI job reruns Vitest and production Vite build.
- CI uses deterministic fakes/adapters and intentionally does not start credentialed live OpenAI/Discord/Notion work automatically; live credential checks remain local UAT and are not required to merge this code-only recovery branch.

## Merge rule
R0→R5 are now all PASS. The implementation is merge-eligible only after the user explicitly authorizes merging PR #23. Do not merge on PASS alone.

## Current gate
**R0 PASS → R1 PASS → R2 PASS → R3 PASS → R4 PASS → R5 PASS → AWAITING EXPLICIT USER MERGE APPROVAL.**
