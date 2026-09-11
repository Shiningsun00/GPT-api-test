from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import Artifact, Revision


def artifact_index(artifacts: Iterable[Artifact]) -> dict[str, Artifact]:
    return {artifact.id: artifact for artifact in artifacts}


def newest_artifact(artifacts: Iterable[Artifact], kind: str) -> Artifact | None:
    matches = [artifact for artifact in artifacts if artifact.kind == kind]
    if not matches:
        return None
    return max(matches, key=lambda artifact: (artifact.sequence, artifact.created_at, artifact.id))


def validate_artifact_dependencies(artifact: Artifact, completed: Mapping[str, Artifact]) -> None:
    missing = [dependency for dependency in artifact.dependencies if dependency not in completed]
    if missing:
        raise ValueError(f"artifact has unresolved dependencies: {missing}")


def next_revision_version(revisions: Iterable[Revision]) -> int:
    versions = [revision.version for revision in revisions]
    return max(versions, default=0) + 1
