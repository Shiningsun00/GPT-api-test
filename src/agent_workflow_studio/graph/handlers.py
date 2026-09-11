from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .state import WorkflowGraphState, assert_checkpoint_safe


@dataclass(frozen=True, slots=True)
class UserInputRequest:
    question: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("user input question is required")
        assert_checkpoint_safe(dict(self.payload), "user_input_request.payload")


@dataclass(frozen=True, slots=True)
class StageResult:
    output: str
    artifact_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.output, str):
            raise TypeError("stage output must be a string")
        if self.artifact_ref is not None and not isinstance(self.artifact_ref, str):
            raise TypeError("artifact_ref must be a string or None")
        assert_checkpoint_safe(dict(self.metadata), "stage_result.metadata")


class StageHandler(Protocol):
    """A generic stage boundary used by STEP 3.

    `request_input` must be side-effect free because LangGraph restarts an
    interrupted node from the beginning when it is resumed. External side effects
    belong in `execute`, which runs only after the human gate has completed.
    """

    def request_input(self, state: WorkflowGraphState, stage: str) -> UserInputRequest | None:
        ...

    def execute(self, state: WorkflowGraphState, stage: str, human_input: Any | None) -> StageResult:
        ...


ExecuteFn = Callable[[WorkflowGraphState, str, Any | None], StageResult]
RequestFn = Callable[[WorkflowGraphState, str], UserInputRequest | None]


class FunctionStageHandler:
    def __init__(self, execute: ExecuteFn, request_input: RequestFn | None = None) -> None:
        self._execute = execute
        self._request_input = request_input

    def request_input(self, state: WorkflowGraphState, stage: str) -> UserInputRequest | None:
        if self._request_input is None:
            return None
        return self._request_input(state, stage)

    def execute(self, state: WorkflowGraphState, stage: str, human_input: Any | None) -> StageResult:
        return self._execute(state, stage, human_input)
