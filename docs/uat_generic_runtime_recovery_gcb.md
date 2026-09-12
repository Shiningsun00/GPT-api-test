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
- [x] Generic=`policy_id=None`, Career=`career_cover_letter`.
- [x] Policy-specific role binding lives at Workflow/WorkerSlot level, not Agent name.
- [x] Generic Linear / Hierarchical semantics fixed.
- [x] Conservative legacy Career compatibility fixed.
- [x] PRD compliance review = PASS.

## R1 — Domain / Persistence Policy Separation — PASS
- [x] Durable Workflow policy/template representation.
- [x] Generic default for new Workflows.
- [x] Policy-specific role bindings at Workflow/slot level.
- [x] SQLite v1→v2 migration/reopen safety.
- [x] Secret-like policy config rejection.
- [x] PRD compliance review = PASS.

## R2 — Generic Runtime — PASS
- [x] Generic Linear arbitrary Agents.
- [x] Generic Hierarchical Manager + N Workers, including N=2.
- [x] Arbitrary Agent names; duplicate Agent / distinct WorkerSlots.
- [x] Initial/follow-up files, same-Run HITL, Manual Resume, Continuation Run.
- [x] PRD compliance review = PASS.

## R3 — Runtime Router / FastAPI — PASS
- [x] Stored Workflow policy decides runtime.
- [x] Generic → `GenericWorkflowRuntime`; Career → `CareerWorkflowRuntime`.
- [x] `/runs/with-files`, Resume/history, Follow-up are policy-aware.
- [x] Career runtime uses explicit WorkerSlot role bindings, not Agent names.
- [x] Generic Manager + 2 Worker API E2E and Career regression PASS.
- [x] Client policy override rejection PASS.
- [x] PRD compliance review = PASS.

## R4 — Local UI / Template UX — PASS
- [x] Workflow form exposes Generic / Career policy selection; Generic default.
- [x] Agent examples are domain-neutral.
- [x] Career W1–W6 mapping appears only at WorkerSlot level.
- [x] Career role and duplicate slot pre-validation.
- [x] Generic Manager + 2 Worker UI contract + backend execution path PASS.
- [x] Issue #21 API-base UX fixed and regression-tested.
- [x] UI/Vitest 11 tests + Vite production build PASS.
- [x] PRD compliance review = PASS.

## R5 — Regression / UAT Merge Gate — PASS
- [x] Generic Hierarchical Manager + 2 arbitrary Workers → Final.
- [x] Generic Linear 2+ arbitrary Agents → Final.
- [x] No W1–W6 Agent-name dependency in Generic.
- [x] Duplicate Agent / distinct WorkerSlots.
- [x] Career explicit WorkerSlot W1–W6 role binding with arbitrary Agent names.
- [x] Initial Run + execution file durability/routing.
- [x] Agent-requested HITL → same Run/thread Resume.
- [x] Worker failure → explicit Manual Resume without replaying completed work.
- [x] Completed result → Follow-up + file → Continuation Run + new Revision.
- [x] Restart/reopen does not auto-resume external/API work.
- [x] Artifact / Revision append-only and historical immutability.
- [x] Discord / Notion regressions.
- [x] Backup / validate / import / restore / cleanup regressions.
- [x] Existing Final Acceptance 1–19 PASS.
- [x] Dedicated `manual_r5_recovery_acceptance.py` PASS.
- [x] 108 Python unit/boundary tests PASS.
- [x] UI/Vitest 11 tests PASS and Vite production build PASS.
- [x] Final branch-head GitHub Actions run `34667893871`: `unit-tests` SUCCESS and `local-ui` SUCCESS, including explicit R5 recovery gate.
- [x] **R5 FINAL PRD compliance = PASS.**

### R5 PRD compliance review
The recovery branch was re-checked against approved PRD v1.0 Product Vision, P1–P8, FR-01/04/05/06/07/08/09/10/11/12/14/15, Career Policy invariants, NFR-01/02/04/05/07/08, D-01/03/04/05/06/07/08/09/10, and C-01. The correction restores the generic-first architecture rather than changing product scope: domain policy remains separated from Core, Agents remain reusable, local persistence/checkpoints remain authoritative, terminal Runs are not reactivated, follow-up files remain turn-scoped, and external integrations keep their existing safety boundaries. No new Product Decision outside PRD v1.0 was required by R5.

### Validation boundary
CI uses deterministic fakes/adapters and intentionally does not start credentialed live OpenAI/Discord/Notion work automatically. Those live-credential checks remain optional local UAT and are not required for this code-only recovery merge gate.

## Merge rule
R0→R5 are all PASS. The implementation is merge-eligible only after the user explicitly authorizes merging PR #23. Do not merge on PASS alone.

## Current gate
**R0 PASS → R1 PASS → R2 PASS → R3 PASS → R4 PASS → R5 PASS → AWAITING EXPLICIT USER MERGE APPROVAL.**
