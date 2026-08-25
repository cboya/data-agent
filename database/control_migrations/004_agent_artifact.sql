CREATE TABLE IF NOT EXISTS agent_artifact (
    id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    run_id VARCHAR(128) NOT NULL,
    artifact_type VARCHAR(32) NOT NULL,
    contract_version VARCHAR(32) NOT NULL,
    payload_json JSON NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_agent_artifact_run_created (run_id, created_at),
    CONSTRAINT fk_agent_artifact_run_session
        FOREIGN KEY (run_id, session_id) REFERENCES agent_run (id, session_id),
    CONSTRAINT chk_agent_artifact_type CHECK (
        artifact_type IN (
            'REQUIREMENT_STATE', 'RETRIEVAL_RESULT', 'QUERY_PLAN', 'SQL_GUARD',
            'EXPLAIN', 'EXECUTION_METADATA', 'VERIFICATION'
        )
    )
) ENGINE=InnoDB;
