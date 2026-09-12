# Agent Workflow Studio 2.0 — Generic Runtime Recovery GCB

Status: R0–R5 PASS / AWAITING MERGE APPROVAL

## Source of Truth
1. `docs/PRD.md` — APPROVED v1.0 (highest priority)
2. `docs/migration_spec.md`
3. `docs/Agent_Workflow_Studio_2.0_Roadmap_GCB.md`
4. merged STEP 0–9 implementation
5. UAT findings / correction issue

## Recovery result
The P0 UAT mismatch is corrected without changing approved product scope: Generic is the default execution model; Career Cover Letter is an explicit Workflow Policy / Template; Agent names remain reusable and policy roles are stored on Workflow/WorkerSlot configuration.

## Cross-cutting invariants
- Generic execution never depends on Career W1–W6 Agent naming.
- Agent identity/name stays reusable; domain roles belong to Workflow/WorkerSlot policy configuration.
- WorkflowSession != Run.
- Agent-requested HITL resumes the same active Run/thread.
- Post-result Follow-up creates a new Continuation Run in the same Session.
- Follow-up files remain turn-scoped by default.
- Artifact / Revision history remains append-only.
- Restart never auto-resumes external/API/LLM work; Manual Resume is explicit.
- Single-user / Local-first and secret boundaries remain unchanged.
- Career Cover Letter remains an explicit policy/template.

## R0 — Architecture Decision — PASS
- [x] Generic=`policy_id=None`; Career=`career_cover_letter`.
- [x] Role binding at Workflow/WorkerSlot level.
- [x] Generic Linear / Hierarchical semantics fixed.
- [x] Conservative legacy Career compatibility.
- [x] PRD compliance PASS.

## R1 — Domain / Persistence Policy Separation — PASS
- [x] Durable Workflow policy/template representation.
- [x] Generic default and WorkerSlot-level role binding.
- [x] SQLite v1→v2 migration/reopen safety.
- [x] Secret-like policy config rejection.
- [x] PRD compliance PASS.

## R2 — Generic Runtime — PASS
- [x] Arbitrary Generic Linear Agents.
- [x] Generic Hierarchical Manager + N Workers, including N=2.
- [x] Arbitrary Agent names and duplicate Agent/distinct WorkerSlots.
- [x] Initial/follow-up files, same-Run HITL, Manual Resume, Continuation Run.
- [x] PRD compliance PASS.

## R3 — Runtime Router / FastAPI — PASS
- [x] Stored Workflow policy selects runtime.
- [x] Generic → `GenericWorkflowRuntime`; Career → `CareerWorkflowRuntime`.
- [x] Run/files/Resume/history/Follow-up are policy-aware.
- [x] Career uses explicit WorkerSlot W1–W6 bindings, not Agent names.
- [x] Generic Manager + 2 Worker API E2E and Career regression PASS.
- [x] Client policy override rejection PASS.
- [x] PRD compliance PASS.

## R4 — Local UI / Template UX — PASS
- [x] Generic / Career selector with Generic default.
- [x] Domain-neutral Agent examples.
- [x] Career W1–W6 mapping only at WorkerSlot level.
- [x] Career role + duplicate slot pre-validation.
- [x] Generic Manager + 2 Worker UI contract and backend path PASS.
- [x] Issue #21 API-base connection UX fixed and regression-tested.
- [x] UI/Vitest 11 tests and production Vite build PASS.
- [x] PRD compliance PASS.

## R5 — Regression / UAT Merge Gate — PASS
- [x] Generic Hierarchical Manager + 2 arbitrary Workers → Final.
- [x] Generic Linear 2+ arbitrary Agents → Final.
- [x] No W1–W6 Agent-name dependency in Generic.
- [x] Duplicate Agent / distinct WorkerSlots.
- [x] Career explicit WorkerSlot W1–W6 binding with arbitrary Agent names.
- [x] Initial Run + execution file durability/routing.
- [x] Agent HITL → same Run/thread Resume.
- [x] Worker failure → explicit Manual Resume without replaying completed work.
- [x] Completed result → Follow-up + file → Continuation Run + new Revision.
- [x] Restart/reopen does not auto-resume external/API work.
- [x] Artifact / Revision immutability/history preservation.
- [x] Discord / Notion regressions.
- [x] Backup / validate / import / restore / cleanup regressions.
- [x] Final Acceptance 1–19 PASS.
- [x] Dedicated R5 recovery acceptance PASS.
- [x] 108 Python unit/boundary tests PASS.
- [x] UI/Vitest 11 tests + production build PASS.
- [x] Branch-head PR CI `34668128168`: `unit-tests` SUCCESS + `local-ui` SUCCESS, including explicit R5 recovery gate.
- [x] **R5 FINAL PRD compliance = PASS.**

### Validation boundary
CI uses deterministic fakes/adapters and intentionally does not start credentialed live OpenAI/Discord/Notion work automatically. Live-credential checks remain optional local UAT and are not required for this code-only recovery merge gate.

## Merge rule
R0→R5 are all PASS. PR #23 is merge-eligible only after explicit user merge authorization. Do not merge on PASS alone.

## Current gate
**R0 PASS → R1 PASS → R2 PASS → R3 PASS → R4 PASS → R5 PASS → AWAITING EXPLICIT USER MERGE APPROVAL.**
