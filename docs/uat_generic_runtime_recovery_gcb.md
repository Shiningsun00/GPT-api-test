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

## R0 — Gap Freeze / Architecture Decision
### Goal
Freeze the exact PRD mismatch and decide the smallest correction architecture before implementation.

### Context
- PRD positions the product as a general-purpose Workflow Studio.
- Workflow creation journey includes execution-policy selection.
- Current API execution path is Career-only.
- Generic LangGraph/domain foundations already exist and should be reused rather than replaced.

### Boundary
- No production behavior change in this checkpoint.
- No removal of Career runtime.
- No premature Graph editor / Marketplace / multi-user scope.
- Do not encode domain roles in Agent names.

### Gate
- [ ] Map all Career hard-wiring points in API / runtime / UI / persistence.
- [ ] Decide where `workflow policy/template` is stored and how old rows are migrated safely.
- [ ] Decide how policy-specific role binding is represented without Agent-name coupling.
- [ ] Define Generic Linear and Generic Hierarchical execution semantics.
- [ ] Define backward-compatibility behavior for existing Career workflows.
- [ ] PRD compliance review = PASS.

## R1 — Domain / Persistence Policy Separation
### Goal
Represent Generic vs domain Policy/Template explicitly in durable Workflow configuration.

### Context
Generic execution must be the default product capability, while Career is an optional policy/template.

### Boundary
- Existing WorkflowSession/Run/Artifact/Revision semantics unchanged.
- Existing stored workflows must migrate deterministically; no silent data loss.
- Agent records remain domain-agnostic.

### Gate
- [ ] Durable Workflow policy/template field or equivalent is implemented.
- [ ] Generic is the default for newly created generic workflows.
- [ ] Policy-specific role bindings are stored at Workflow/slot level, not inferred from Agent name.
- [ ] SQLite migration is versioned/idempotent and reopen-safe.
- [ ] Existing Career workflows retain a compatible migration path.
- [ ] Domain/persistence tests PASS.
- [ ] PRD compliance review = PASS.

## R2 — Generic Runtime
### Goal
Allow arbitrary user-defined Linear and Hierarchical workflows to execute without Career W1–W6 requirements.

### Context
Primary UAT target is a Hierarchical workflow with one Manager and two arbitrary Workers.

### Boundary
- Reuse existing durable LangGraph/checkpoint machinery.
- No domain-specific stage names or role validation in Generic runtime.
- Preserve Worker Slot ID != Agent ID and duplicate-Agent-slot support.
- Preserve HITL, attachments, restart/manual-resume, and append-only history rules.

### Gate
- [ ] Generic Linear runtime works for arbitrary ordered Agents.
- [ ] Generic Hierarchical runtime works for Manager + N Workers (including N=2).
- [ ] Agent names are unrestricted in Generic runtime.
- [ ] Duplicate Agent in distinct Worker Slots remains valid.
- [ ] Initial files and turn-scoped follow-up files are available according to routing semantics.
- [ ] HITL same-Run Resume and error Manual Resume remain valid.
- [ ] Post-result follow-up creates a Continuation Run, not reactivation.
- [ ] Generic runtime tests PASS.
- [ ] PRD compliance review = PASS.

## R3 — Runtime Router / FastAPI
### Goal
Route a Run to the Workflow's selected policy/runtime rather than hard-wiring Career.

### Context
Clients should start a Workflow; the backend should resolve its durable execution policy.

### Boundary
- Do not trust a client default that can silently override the stored Workflow policy.
- Preserve current API compatibility where reasonably possible.
- Career runtime remains available only when the Workflow explicitly selects it.

### Gate
- [ ] Run start resolves policy from Workflow configuration.
- [ ] Generic workflow invokes Generic runtime.
- [ ] Career workflow invokes Career runtime.
- [ ] Generic Manager + 2 Worker API E2E PASS.
- [ ] Career API regression PASS.
- [ ] Resume/follow-up routing selects the correct runtime for the Run's Workflow.
- [ ] Error responses distinguish invalid generic structure from policy-specific validation.
- [ ] PRD compliance review = PASS.

## R4 — Local UI / Template UX
### Goal
Make the generic-first model obvious and prevent the UI from implying Career-specific naming rules for normal Agents.

### Context
Users create reusable Agents and then assign them inside a Workflow. Career role requirements should appear only when Career policy/template is selected.

### Boundary
- Form/List editor remains the 2.0 UX; no Visual Node Editor expansion.
- No OpenAI/Notion/Discord secret fields in browser UI.

### Gate
- [ ] Workflow form exposes Generic vs Career policy/template selection.
- [ ] Generic is the default.
- [ ] Generic Agent name examples are domain-neutral.
- [ ] Career-only role mapping UI appears only for Career policy.
- [ ] UI validates missing/duplicate Career roles before execution/save where appropriate.
- [ ] Manager + 2 Worker Generic workflow can be created and started from UI.
- [ ] Existing UAT API-base connection issue remains tracked/fixed with regression coverage.
- [ ] UI tests/build PASS.
- [ ] PRD compliance review = PASS.

## R5 — Regression / UAT Gate
### Goal
Prove that restoring Generic execution did not break Career or cross-cutting durability guarantees.

### Context
This is the merge gate for the correction track.

### Boundary
No PASS based only on unit tests; include end-to-end credential-free and user-facing scenarios.

### Gate
- [ ] Generic Hierarchical: Manager + 2 arbitrary Workers → final result.
- [ ] Generic Linear: 2+ arbitrary Agents → final result.
- [ ] Generic arbitrary names (no W1–W6) PASS.
- [ ] Duplicate Agent / distinct Worker Slots PASS.
- [ ] Career Cover Letter W1–W6 template regression PASS using explicit role binding.
- [ ] Initial Run + file PASS.
- [ ] Agent HITL → same Run/thread Resume PASS.
- [ ] Worker failure → Manual Resume PASS.
- [ ] Completed result → follow-up + file → Continuation Run + new Revision PASS.
- [ ] Restart does not auto-call external APIs PASS.
- [ ] Artifact/Revision history immutability PASS.
- [ ] Discord and Notion adapter regressions PASS against policy-aware routing.
- [ ] Backup/import/recovery regression PASS.
- [ ] React tests/build PASS.
- [ ] PRD compliance review = PASS.

## Merge rule
No implementation PR is merged until R0–R5 relevant gates are checked and the final PRD compliance review is PASS. If a checkpoint exposes a new product decision not fixed by PRD v1.0, stop and ask the user before implementing that decision.
