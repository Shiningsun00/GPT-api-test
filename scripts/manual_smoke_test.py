from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_workflow_studio.core.models import RunStatus, Workflow
from agent_workflow_studio.core.workflow import new_initial_run, new_session
from agent_workflow_studio.graph import (
    DurableGraphEngine,
    FunctionStageHandler,
    SQLiteGraphCheckpointer,
    StageResult,
    UserInputRequest,
    build_graph_state,
)
from agent_workflow_studio.persistence import DurableWorkflowService, LocalFileStore, PendingAttachment, SQLitePersistence


def main() -> int:
    parser = argparse.ArgumentParser(description="STEP 3 LangGraph manual smoke test")
    parser.add_argument("--auto", action="store_true", help="Use automatic HITL answers instead of prompting")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="aws-step3-") as tmp:
        root = Path(tmp)
        domain_path = root / "domain.sqlite"
        checkpoint_path = root / "checkpoints.sqlite"
        file_root = root / "files"

        persistence = SQLitePersistence(domain_path)
        file_store = LocalFileStore(file_root)
        workflow = Workflow(id="manual-workflow", name="STEP 3 Manual Smoke")
        persistence.workflows.save(workflow)
        session = new_session(workflow, session_id="manual-session")
        persistence.sessions.save(session)
        initial = new_initial_run(session, run_id="manual-run-1")
        persistence.runs.save(initial)

        def collect(state, stage, human):
            return StageResult(output="evidence-collected", artifact_ref=f"artifact://{state['run_id']}/collect")

        def ask_request(state, stage):
            return UserInputRequest("계속 진행할까요? yes/no")

        def approve(state, stage, human):
            return StageResult(output=f"approved:{human}", artifact_ref=f"artifact://{state['run_id']}/approve")

        print("[1/4] Initial Run 시작")
        cp = SQLiteGraphCheckpointer(checkpoint_path)
        engine = DurableGraphEngine(
            {
                "collect": FunctionStageHandler(collect),
                "approve": FunctionStageHandler(approve, ask_request),
            },
            cp,
            persistence=persistence,
        )
        waiting = engine.start(
            build_graph_state(
                session_id=session.id,
                run_id=initial.id,
                stages=["collect", "approve"],
                user_request="STEP 3 smoke test",
            )
        )
        if waiting.status != RunStatus.WAITING_FOR_USER:
            raise RuntimeError(f"expected WAITING_FOR_USER, got {waiting.status.value}")
        print("      PASS: collect 완료 후 HITL interrupt 발생")
        print(f"      질문: {waiting.state['interrupt_question']}")

        print("[2/4] Checkpointer 종료 후 재오픈 — 자동 Resume는 하지 않음")
        cp.close()
        answer = "yes" if args.auto else input("      답변 입력 (예: yes): ").strip() or "yes"
        reopened_cp = SQLiteGraphCheckpointer(checkpoint_path)
        reopened = DurableGraphEngine(
            {
                "collect": FunctionStageHandler(collect),
                "approve": FunctionStageHandler(approve, ask_request),
            },
            reopened_cp,
            persistence=persistence,
        )
        if persistence.runs.get(initial.id).status != RunStatus.WAITING_FOR_USER:
            raise RuntimeError("Run status changed before explicit Resume")
        if reopened.get_state(initial.id)["completed_stages"] != ["collect"]:
            raise RuntimeError("completed stage was not restored from checkpoint")
        completed = reopened.resume_with_user(initial.id, answer)
        if not completed.completed:
            raise RuntimeError(f"resume did not complete: {completed.status.value}")
        print("      PASS: 같은 Run/thread에서 명시적 HITL Resume 완료")

        print("[3/4] Manager 결과 이후 Follow-up + 파일 → Continuation Run")
        durable = DurableWorkflowService(persistence, file_store)
        followup = durable.persist_followup(
            session_id=session.id,
            previous_run_id=initial.id,
            content="첨부 근거를 반영해 다시 처리해줘",
            uploads=[PendingAttachment(filename="evidence.txt", data=b"manual follow-up evidence")],
            message_id="manual-message-2",
            run_id="manual-run-2",
        )

        seen_refs: list[str] = []

        def revise(state, stage, human):
            seen_refs.extend(state["follow_up_attachment_refs"])
            return StageResult(output="revision-created", artifact_ref=f"artifact://{state['run_id']}/revise")

        follow_engine = DurableGraphEngine(
            {"revise": FunctionStageHandler(revise)},
            reopened_cp,
            persistence=persistence,
        )
        follow_result = follow_engine.start_followup(followup, stages=["revise"])
        if not follow_result.completed:
            raise RuntimeError(f"follow-up run failed: {follow_result.status.value}")
        if follow_result.thread_id != followup.run.id or follow_result.thread_id == initial.id:
            raise RuntimeError("Continuation Run did not receive a new graph thread")
        if seen_refs != [followup.attachments[0].storage_ref]:
            raise RuntimeError("Follow-up attachment reference was not delivered")
        print("      PASS: 새 Continuation Run/thread + attachment reference 전달")

        print("[4/4] Worker 오류 → Manual Resume")
        second_session = new_session(workflow, session_id="manual-session-2")
        persistence.sessions.save(second_session)
        error_run = new_initial_run(second_session, run_id="manual-run-3")
        persistence.runs.save(error_run)
        attempts = {"count": 0}

        def flaky(state, stage, human):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("intentional smoke-test failure")
            return StageResult(output="recovered")

        error_engine = DurableGraphEngine(
            {"flaky": FunctionStageHandler(flaky)},
            reopened_cp,
            persistence=persistence,
        )
        paused = error_engine.start(
            build_graph_state(session_id=second_session.id, run_id=error_run.id, stages=["flaky"])
        )
        if paused.status != RunStatus.PAUSED:
            raise RuntimeError(f"expected PAUSED, got {paused.status.value}")
        if not args.auto:
            input("      오류가 PAUSED로 저장되었습니다. Enter를 눌러 Manual Resume: ")
        recovered = error_engine.resume_after_error(error_run.id)
        if not recovered.completed or attempts["count"] != 2:
            raise RuntimeError("failed node did not recover correctly")
        print("      PASS: failed node만 재실행되어 완료")

        reopened_cp.close()
        persistence.close()
        print("\nSTEP 3 MANUAL SMOKE TEST = PASS")
        print("검증: persistent checkpoint / no auto-resume / HITL / continuation thread / attachment refs / error resume")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
