from __future__ import annotations

CURRENT_SCHEMA_VERSION = 2

REQUIRED_TABLES = frozenset(
    {
        "schema_migrations",
        "agents",
        "sources",
        "agent_sources",
        "workflows",
        "workflow_nodes",
        "workflow_workers",
        "workflow_sessions",
        "runs",
        "messages",
        "message_attachments",
        "artifacts",
        "artifact_dependencies",
        "revisions",
        "revision_artifacts",
        "revision_attachments",
        "execution_events",
        "run_files",
        "run_file_targets",
        "external_thread_links",
    }
)

MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model TEXT NOT NULL,
            system_prompt TEXT NOT NULL DEFAULT '',
            rag_enabled INTEGER NOT NULL DEFAULT 0 CHECK (rag_enabled IN (0, 1)),
            rag_top_k INTEGER NOT NULL DEFAULT 5 CHECK (rag_top_k >= 1),
            notion_enabled INTEGER NOT NULL DEFAULT 0 CHECK (notion_enabled IN (0, 1)),
            notion_sources_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('file', 'notion')),
            label TEXT NOT NULL,
            sha256 TEXT,
            storage_ref TEXT,
            notion_ref TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE agent_sources (
            agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (agent_id, source_id)
        )
        """,
        """
        CREATE TABLE workflows (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('linear', 'hierarchical', 'graph')),
            include_original_prompt INTEGER NOT NULL DEFAULT 1 CHECK (include_original_prompt IN (0, 1)),
            has_hierarchy INTEGER NOT NULL DEFAULT 0 CHECK (has_hierarchy IN (0, 1)),
            manager_agent_id TEXT REFERENCES agents(id) ON DELETE RESTRICT,
            manager_planning_prompt TEXT NOT NULL DEFAULT '',
            manager_synthesis_prompt TEXT NOT NULL DEFAULT '',
            manager_routing_prompt TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE workflow_nodes (
            workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            step_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
            additional_prompt TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (workflow_id, step_id)
        )
        """,
        """
        CREATE TABLE workflow_workers (
            workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            worker_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
            additional_prompt TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (workflow_id, worker_id)
        )
        """,
        """
        CREATE TABLE workflow_sessions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE RESTRICT,
            title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES workflow_sessions(id) ON DELETE CASCADE,
            workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE RESTRICT,
            kind TEXT NOT NULL CHECK (kind IN ('initial', 'continuation')),
            status TEXT NOT NULL CHECK (status IN ('CREATED', 'RUNNING', 'WAITING_FOR_USER', 'PAUSED', 'FAILED', 'CANCELLED', 'COMPLETED')),
            parent_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
            trigger_message_id TEXT REFERENCES messages(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        )
        """,
        """
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES workflow_sessions(id) ON DELETE CASCADE,
            run_id TEXT REFERENCES runs(id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
            role TEXT NOT NULL CHECK (role IN ('user', 'manager', 'agent', 'system')),
            content TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE message_attachments (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL CHECK (size >= 0),
            storage_ref TEXT NOT NULL,
            scope TEXT NOT NULL CHECK (scope IN ('turn', 'run')),
            mime_type TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES workflow_sessions(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            producer TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            sequence INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE artifact_dependencies (
            artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
            depends_on_artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE RESTRICT,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (artifact_id, depends_on_artifact_id)
        )
        """,
        """
        CREATE TABLE revisions (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES workflow_sessions(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            version INTEGER NOT NULL CHECK (version >= 1),
            final_output TEXT NOT NULL DEFAULT '',
            feedback TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE (session_id, version)
        )
        """,
        """
        CREATE TABLE revision_artifacts (
            revision_id TEXT NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE RESTRICT,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (revision_id, artifact_id)
        )
        """,
        """
        CREATE TABLE revision_attachments (
            revision_id TEXT NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
            attachment_id TEXT NOT NULL REFERENCES message_attachments(id) ON DELETE RESTRICT,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (revision_id, attachment_id)
        )
        """,
        """
        CREATE TABLE execution_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES workflow_sessions(id) ON DELETE CASCADE,
            run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT '',
            data_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE run_files (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL CHECK (size >= 0),
            storage_ref TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE run_file_targets (
            run_file_id TEXT NOT NULL REFERENCES run_files(id) ON DELETE CASCADE,
            target_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (run_file_id, target_id)
        )
        """,
        """
        CREATE TABLE external_thread_links (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            external_thread_id TEXT NOT NULL,
            session_id TEXT NOT NULL REFERENCES workflow_sessions(id) ON DELETE CASCADE,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (provider, external_thread_id)
        )
        """,
        "CREATE INDEX idx_agent_sources_agent ON agent_sources(agent_id, position)",
        "CREATE INDEX idx_workflow_nodes_workflow ON workflow_nodes(workflow_id, position)",
        "CREATE INDEX idx_workflow_workers_workflow ON workflow_workers(workflow_id, position)",
        "CREATE INDEX idx_runs_session ON runs(session_id, created_at)",
        "CREATE UNIQUE INDEX ux_runs_single_active ON runs((1)) WHERE status IN ('CREATED', 'RUNNING', 'WAITING_FOR_USER')",
        "CREATE INDEX idx_messages_session ON messages(session_id, created_at)",
        "CREATE INDEX idx_messages_run ON messages(run_id, created_at)",
        "CREATE INDEX idx_attachments_message ON message_attachments(message_id, created_at)",
        "CREATE INDEX idx_artifacts_run ON artifacts(run_id, sequence, created_at)",
        "CREATE INDEX idx_revisions_session ON revisions(session_id, version)",
        "CREATE INDEX idx_events_run ON execution_events(run_id, created_at)",
        "CREATE INDEX idx_run_files_run ON run_files(run_id, created_at)",
        "CREATE INDEX idx_external_links_session ON external_thread_links(session_id, provider)",
    ),
    2: (
        "ALTER TABLE workflows ADD COLUMN policy_id TEXT",
        "ALTER TABLE workflows ADD COLUMN policy_config_json TEXT NOT NULL DEFAULT '{}'",
    ),
}
