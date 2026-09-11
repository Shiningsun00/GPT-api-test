from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any, Mapping

from agent_workflow_studio.core.models import ReferenceSource, ReferenceSourceKind
from agent_workflow_studio.core.workflow import validate_workflow
from agent_workflow_studio.persistence import LocalFileStore, SQLitePersistence

from .workspace_v4 import (
    legacy_agent_to_core,
    legacy_hierarchy_to_workflow,
    legacy_linear_to_workflow,
    validate_schema_version,
)

_MAX_FILES = 1000
_MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
_MAX_MANIFEST_BYTES = 5 * 1024 * 1024
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "openai_api_key",
    "notion_api_key",
    "notion_token",
    "notion_api_token",
    "discord_token",
    "discord_bot_token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "client_secret",
}


class LegacyWorkspaceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LegacyWorkspaceImportReport:
    schema_version: int
    workspace_digest: str
    imported_agents: tuple[str, ...]
    skipped_agents: tuple[str, ...]
    imported_workflows: tuple[str, ...]
    imported_sources: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workspace_digest": self.workspace_digest,
            "imported_agents": list(self.imported_agents),
            "skipped_agents": list(self.skipped_agents),
            "imported_workflows": list(self.imported_workflows),
            "imported_sources": list(self.imported_sources),
            "warnings": list(self.warnings),
        }


def _safe_zip_name(name: str) -> str:
    if "\\" in name:
        raise LegacyWorkspaceError(f"unsafe ZIP path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise LegacyWorkspaceError(f"unsafe ZIP path: {name}")
    return path.as_posix()


def _normalized_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _strip_secrets(value: Any, warnings: list[str], path: str = "manifest") -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if _normalized_key(key) in _SECRET_KEYS:
                warnings.append(f"ignored secret-like field: {path}.{key}")
                continue
            clean[str(key)] = _strip_secrets(item, warnings, f"{path}.{key}")
        return clean
    if isinstance(value, list):
        return [_strip_secrets(item, warnings, f"{path}[]") for item in value]
    return value


def _agent_items(raw: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(raw, Mapping):
        return [(str(key), dict(value)) for key, value in raw.items() if isinstance(value, Mapping)]
    if isinstance(raw, list):
        result = []
        for index, value in enumerate(raw, start=1):
            if not isinstance(value, Mapping):
                continue
            data = dict(value)
            key = str(data.get("id") or f"agent-{index}")
            result.append((key, data))
        return result
    if raw in (None, ""):
        return []
    raise LegacyWorkspaceError("manifest.agents must be an object or list")


class LegacyWorkspaceImporter:
    """Import-only bridge from legacy Workspace ZIP schemas 1-4 into 2.0 persistence."""

    def __init__(self, persistence: SQLitePersistence, file_store: LocalFileStore) -> None:
        self.persistence = persistence
        self.file_store = file_store

    def _read_zip(self, data: bytes) -> tuple[dict[str, Any], dict[str, bytes], list[str]]:
        warnings: list[str] = []
        try:
            archive = zipfile.ZipFile(io.BytesIO(data), "r")
        except zipfile.BadZipFile as exc:
            raise LegacyWorkspaceError("legacy workspace is not a valid ZIP file") from exc
        with archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            if len(infos) > _MAX_FILES:
                raise LegacyWorkspaceError(f"legacy workspace contains too many files: {len(infos)}")
            if sum(item.file_size for item in infos) > _MAX_UNCOMPRESSED_BYTES:
                raise LegacyWorkspaceError("legacy workspace exceeds the uncompressed size limit")
            names = {_safe_zip_name(item.filename): item for item in infos}
            if "manifest.json" not in names:
                raise LegacyWorkspaceError("legacy workspace manifest.json is missing")
            if names["manifest.json"].file_size > _MAX_MANIFEST_BYTES:
                raise LegacyWorkspaceError("legacy workspace manifest.json is too large")
            try:
                raw_manifest = json.loads(archive.read(names["manifest.json"]).decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LegacyWorkspaceError("legacy workspace manifest.json is invalid") from exc
            if not isinstance(raw_manifest, Mapping):
                raise LegacyWorkspaceError("legacy workspace manifest must be a JSON object")
            manifest = _strip_secrets(dict(raw_manifest), warnings)
            payloads = {name: archive.read(info) for name, info in names.items() if name != "manifest.json"}
            return manifest, payloads, warnings

    def _locate_rag_file(
        self,
        payloads: Mapping[str, bytes],
        *,
        agent_keys: tuple[str, ...],
        metadata: Mapping[str, Any],
    ) -> tuple[str, bytes] | None:
        explicit = str(metadata.get("path") or metadata.get("zip_path") or "").strip()
        if explicit:
            safe = _safe_zip_name(explicit)
            if safe in payloads:
                return safe, payloads[safe]
        filename = PurePosixPath(str(metadata.get("name") or metadata.get("filename") or "")).name
        candidates: list[tuple[str, bytes]] = []
        for key in agent_keys:
            prefix = f"rag_files/{key}/"
            for name, data in payloads.items():
                if name.startswith(prefix) and (not filename or PurePosixPath(name).name == filename):
                    candidates.append((name, data))
        expected_hash = str(metadata.get("sha256") or "").strip().lower()
        if expected_hash:
            hashed = [item for item in candidates if hashlib.sha256(item[1]).hexdigest() == expected_hash]
            if len(hashed) == 1:
                return hashed[0]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def import_bytes(self, data: bytes, *, conflict_policy: str = "fail") -> LegacyWorkspaceImportReport:
        if conflict_policy not in {"fail", "skip"}:
            raise LegacyWorkspaceError("conflict_policy must be 'fail' or 'skip'")
        manifest, payloads, warnings = self._read_zip(data)
        schema_version = validate_schema_version(int(manifest.get("schema_version", 1)))
        digest = hashlib.sha256(data).hexdigest()
        suffix = digest[:12]
        raw_agents = _agent_items(manifest.get("agents", {}))
        imported_agents: list[str] = []
        skipped_agents: list[str] = []
        imported_sources: list[str] = []
        prepared_agents = []

        for key, agent_data in raw_agents:
            agent_id = str(agent_data.get("id") or key)
            if self.persistence.agents.get(agent_id) is not None:
                if conflict_policy == "fail":
                    raise LegacyWorkspaceError(f"agent already exists: {agent_id}")
                skipped_agents.append(agent_id)
                continue
            rag_metadata = [dict(item) for item in (agent_data.get("rag_files") or []) if isinstance(item, Mapping)]
            known_names = {str(item.get("name") or item.get("filename") or "") for item in rag_metadata}
            for agent_key in (key, agent_id):
                prefix = f"rag_files/{agent_key}/"
                for path, payload in payloads.items():
                    if path.startswith(prefix):
                        name = PurePosixPath(path).name
                        if name not in known_names:
                            rag_metadata.append({"name": name, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload), "path": path})
                            known_names.add(name)
            source_ids: list[str] = []
            sources: list[ReferenceSource] = []
            for item in rag_metadata:
                located = self._locate_rag_file(payloads, agent_keys=(key, agent_id), metadata=item)
                if located is None:
                    warnings.append(f"RAG file not found for agent {agent_id}: {item.get('name', '[unnamed]')}")
                    continue
                path, payload = located
                actual_hash = hashlib.sha256(payload).hexdigest()
                expected_hash = str(item.get("sha256") or "").strip().lower()
                if expected_hash and expected_hash != actual_hash:
                    raise LegacyWorkspaceError(f"RAG sha256 mismatch: {path}")
                expected_size = item.get("size")
                if expected_size not in (None, "") and int(expected_size) != len(payload):
                    raise LegacyWorkspaceError(f"RAG size mismatch: {path}")
                stored = self.file_store.store_source(payload)
                source_id = f"file:{actual_hash}"
                source_ids.append(source_id)
                sources.append(
                    ReferenceSource(
                        id=source_id,
                        kind=ReferenceSourceKind.FILE,
                        label=str(item.get("name") or PurePosixPath(path).name),
                        sha256=actual_hash,
                        storage_ref=stored.storage_ref,
                    )
                )
            agent_data = dict(agent_data)
            agent_data["id"] = agent_id
            agent_data["rag_files"] = []
            agent = replace(legacy_agent_to_core(agent_id, agent_data), source_ids=list(dict.fromkeys(source_ids)))
            prepared_agents.append((agent, sources))

        workflows = []
        linear = manifest.get("workflow")
        if isinstance(linear, list) and linear:
            workflows.append(
                validate_workflow(
                    legacy_linear_to_workflow(
                        linear,
                        workflow_id=f"legacy-{suffix}-linear",
                        include_original_prompt=bool(manifest.get("include_original_prompt", True)),
                    )
                )
            )
        hierarchy = manifest.get("hierarchy")
        if isinstance(hierarchy, Mapping) and (hierarchy.get("manager_agent_id") or hierarchy.get("workers")):
            workflows.append(
                validate_workflow(
                    legacy_hierarchy_to_workflow(
                        hierarchy,
                        workflow_id=f"legacy-{suffix}-hierarchical",
                    )
                )
            )
        for workflow in workflows:
            if self.persistence.workflows.get(workflow.id) is not None:
                if conflict_policy == "fail":
                    raise LegacyWorkspaceError(f"workflow already exists: {workflow.id}")
                warnings.append(f"skipped existing workflow: {workflow.id}")

        imported_workflows: list[str] = []
        with self.persistence.db.transaction():
            for agent, sources in prepared_agents:
                for source in sources:
                    self.persistence.sources.save(source)
                    if source.id not in imported_sources:
                        imported_sources.append(source.id)
                self.persistence.agents.save(agent)
                imported_agents.append(agent.id)
            for workflow in workflows:
                if self.persistence.workflows.get(workflow.id) is not None:
                    continue
                self.persistence.workflows.save(workflow)
                imported_workflows.append(workflow.id)
        return LegacyWorkspaceImportReport(
            schema_version=schema_version,
            workspace_digest=digest,
            imported_agents=tuple(imported_agents),
            skipped_agents=tuple(skipped_agents),
            imported_workflows=tuple(imported_workflows),
            imported_sources=tuple(imported_sources),
            warnings=tuple(dict.fromkeys(warnings)),
        )
