from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _encode(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_encode(item) for item in value]
    return value


class Serializable:
    def to_dict(self) -> dict[str, Any]:
        return _encode(self)


class WorkflowMode(str, Enum):
    LINEAR = "linear"
    HIERARCHICAL = "hierarchical"
    GRAPH = "graph"


class RunKind(str, Enum):
    INITIAL = "initial"
    CONTINUATION = "continuation"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"

    @property
    def terminal(self) -> bool:
        return self in {RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.COMPLETED}


class MessageRole(str, Enum):
    USER = "user"
    MANAGER = "manager"
    AGENT = "agent"
    SYSTEM = "system"


class AttachmentScope(str, Enum):
    TURN = "turn"
    RUN = "run"


class ReferenceSourceKind(str, Enum):
    FILE = "file"
    NOTION = "notion"


@dataclass(slots=True)
class ReferenceSource(Serializable):
    id: str
    kind: ReferenceSourceKind
    label: str
    sha256: str | None = None
    storage_ref: str | None = None
    notion_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.kind == ReferenceSourceKind.FILE and not self.storage_ref:
            raise ValueError("file reference sources require storage_ref")
        if self.kind == ReferenceSourceKind.NOTION and not self.notion_ref:
            raise ValueError("notion reference sources require notion_ref")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReferenceSource":
        return cls(id=str(data["id"]), kind=ReferenceSourceKind(data["kind"]), label=str(data.get("label", "")), sha256=data.get("sha256"), storage_ref=data.get("storage_ref"), notion_ref=data.get("notion_ref"), created_at=_dt(data.get("created_at")) or utc_now())


@dataclass(slots=True)
class Agent(Serializable):
    id: str
    name: str
    model: str
    system_prompt: str = ""
    rag_enabled: bool = False
    rag_top_k: int = 5
    source_ids: list[str] = field(default_factory=list)
    notion_enabled: bool = False
    notion_sources: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("agent id is required")
        if not self.name.strip():
            raise ValueError("agent name is required")
        if not self.model.strip():
            raise ValueError("agent model is required")
        if self.rag_top_k < 1:
            raise ValueError("rag_top_k must be at least 1")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Agent":
        return cls(id=str(data["id"]), name=str(data["name"]), model=str(data["model"]), system_prompt=str(data.get("system_prompt", "")), rag_enabled=bool(data.get("rag_enabled", False)), rag_top_k=int(data.get("rag_top_k", 5)), source_ids=[str(item) for item in data.get("source_ids", [])], notion_enabled=bool(data.get("notion_enabled", False)), notion_sources=[str(item) for item in data.get("notion_sources", [])], created_at=_dt(data.get("created_at")) or utc_now(), updated_at=_dt(data.get("updated_at")) or utc_now())


@dataclass(slots=True)
class LinearStep(Serializable):
    step_id: str
    agent_id: str
    additional_prompt: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LinearStep":
        return cls(step_id=str(data["step_id"]), agent_id=str(data["agent_id"]), additional_prompt=str(data.get("additional_prompt", "")))


@dataclass(slots=True)
class WorkerSlot(Serializable):
    worker_id: str
    agent_id: str
    additional_prompt: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkerSlot":
        return cls(worker_id=str(data["worker_id"]), agent_id=str(data["agent_id"]), additional_prompt=str(data.get("additional_prompt", "")))


@dataclass(slots=True)
class HierarchyConfig(Serializable):
    manager_agent_id: str | None = None
    manager_planning_prompt: str = ""
    manager_synthesis_prompt: str = ""
    manager_routing_prompt: str = ""
    workers: list[WorkerSlot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HierarchyConfig":
        return cls(manager_agent_id=data.get("manager_agent_id"), manager_planning_prompt=str(data.get("manager_planning_prompt", "")), manager_synthesis_prompt=str(data.get("manager_synthesis_prompt", "")), manager_routing_prompt=str(data.get("manager_routing_prompt", "")), workers=[WorkerSlot.from_dict(item) for item in data.get("workers", [])])


@dataclass(slots=True)
class Workflow(Serializable):
    id: str
    name: str
    mode: WorkflowMode = WorkflowMode.LINEAR
    steps: list[LinearStep] = field(default_factory=list)
    include_original_prompt: bool = True
    hierarchy: HierarchyConfig | None = None
    policy_id: str | None = None
    policy_config: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.policy_id is not None:
            normalized = str(self.policy_id).strip()
            self.policy_id = normalized or None
        if not isinstance(self.policy_config, Mapping):
            raise TypeError("workflow policy_config must be a mapping")
        self.policy_config = dict(self.policy_config)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Workflow":
        hierarchy = data.get("hierarchy")
        return cls(id=str(data["id"]), name=str(data["name"]), mode=WorkflowMode(data.get("mode", WorkflowMode.LINEAR.value)), steps=[LinearStep.from_dict(item) for item in data.get("steps", [])], include_original_prompt=bool(data.get("include_original_prompt", True)), hierarchy=HierarchyConfig.from_dict(hierarchy) if hierarchy else None, policy_id=data.get("policy_id") or None, policy_config=dict(data.get("policy_config") or {}), created_at=_dt(data.get("created_at")) or utc_now(), updated_at=_dt(data.get("updated_at")) or utc_now())


@dataclass(slots=True)
class WorkflowSession(Serializable):
    id: str
    workflow_id: str
    title: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkflowSession":
        return cls(id=str(data["id"]), workflow_id=str(data["workflow_id"]), title=str(data.get("title", "")), created_at=_dt(data.get("created_at")) or utc_now(), updated_at=_dt(data.get("updated_at")) or utc_now())


@dataclass(slots=True)
class Run(Serializable):
    id: str
    session_id: str
    workflow_id: str
    kind: RunKind = RunKind.INITIAL
    status: RunStatus = RunStatus.CREATED
    parent_run_id: str | None = None
    trigger_message_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.status.terminal

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Run":
        return cls(id=str(data["id"]), session_id=str(data["session_id"]), workflow_id=str(data["workflow_id"]), kind=RunKind(data.get("kind", RunKind.INITIAL.value)), status=RunStatus(data.get("status", RunStatus.CREATED.value)), parent_run_id=data.get("parent_run_id"), trigger_message_id=data.get("trigger_message_id"), created_at=_dt(data.get("created_at")) or utc_now(), updated_at=_dt(data.get("updated_at")) or utc_now(), started_at=_dt(data.get("started_at")), completed_at=_dt(data.get("completed_at")))


@dataclass(slots=True)
class MessageAttachment(Serializable):
    id: str
    message_id: str
    filename: str
    sha256: str
    size: int
    storage_ref: str
    scope: AttachmentScope = AttachmentScope.TURN
    mime_type: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.filename:
            raise ValueError("attachment filename is required")
        if self.size < 0:
            raise ValueError("attachment size cannot be negative")
        if not self.storage_ref:
            raise ValueError("attachment storage_ref is required")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MessageAttachment":
        return cls(id=str(data["id"]), message_id=str(data["message_id"]), filename=str(data["filename"]), sha256=str(data["sha256"]), size=int(data["size"]), storage_ref=str(data["storage_ref"]), scope=AttachmentScope(data.get("scope", AttachmentScope.TURN.value)), mime_type=data.get("mime_type"), created_at=_dt(data.get("created_at")) or utc_now())


@dataclass(slots=True)
class Message(Serializable):
    id: str
    session_id: str
    role: MessageRole
    content: str
    run_id: str | None = None
    attachment_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Message":
        return cls(id=str(data["id"]), session_id=str(data["session_id"]), role=MessageRole(data["role"]), content=str(data.get("content", "")), run_id=data.get("run_id"), attachment_ids=[str(item) for item in data.get("attachment_ids", [])], created_at=_dt(data.get("created_at")) or utc_now())


@dataclass(frozen=True, slots=True)
class Artifact(Serializable):
    id: str
    session_id: str
    run_id: str
    kind: str
    producer: str
    body: str
    dependencies: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Artifact":
        return cls(id=str(data["id"]), session_id=str(data["session_id"]), run_id=str(data["run_id"]), kind=str(data["kind"]), producer=str(data["producer"]), body=str(data.get("body", "")), dependencies=tuple(str(item) for item in data.get("dependencies", [])), metadata=dict(data.get("metadata", {})), sequence=int(data.get("sequence", 0)), created_at=_dt(data.get("created_at")) or utc_now())


@dataclass(frozen=True, slots=True)
class ArtifactDependency(Serializable):
    artifact_id: str
    depends_on_artifact_id: str


@dataclass(frozen=True, slots=True)
class Revision(Serializable):
    id: str
    session_id: str
    run_id: str
    version: int
    final_output: str
    feedback: str = ""
    artifact_ids: tuple[str, ...] = ()
    attachment_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("revision version must be at least 1")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Revision":
        return cls(id=str(data["id"]), session_id=str(data["session_id"]), run_id=str(data["run_id"]), version=int(data["version"]), final_output=str(data.get("final_output", "")), feedback=str(data.get("feedback", "")), artifact_ids=tuple(str(item) for item in data.get("artifact_ids", [])), attachment_ids=tuple(str(item) for item in data.get("attachment_ids", [])), created_at=_dt(data.get("created_at")) or utc_now())


@dataclass(slots=True)
class ExecutionFile(Serializable):
    id: str
    run_id: str
    filename: str
    sha256: str
    size: int
    storage_ref: str
    target_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionFile":
        return cls(id=str(data["id"]), run_id=str(data["run_id"]), filename=str(data["filename"]), sha256=str(data["sha256"]), size=int(data["size"]), storage_ref=str(data["storage_ref"]), target_ids=tuple(str(item) for item in data.get("target_ids", [])), created_at=_dt(data.get("created_at")) or utc_now())
