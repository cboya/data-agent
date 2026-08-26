CREATE TABLE IF NOT EXISTS agent_trace_event (
    id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    run_id VARCHAR(128) NOT NULL,
    sequence BIGINT UNSIGNED NOT NULL,
    attempt TINYINT UNSIGNED NOT NULL,
    stage VARCHAR(32) NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    schema_version VARCHAR(32) NOT NULL,
    payload_json JSON NOT NULL,
    payload_fingerprint CHAR(64) NOT NULL,
    occurred_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_agent_trace_run_sequence (run_id, sequence),
    KEY idx_agent_trace_session_run (session_id, run_id, sequence),
    CONSTRAINT fk_agent_trace_run_session
        FOREIGN KEY (run_id, session_id) REFERENCES agent_run (id, session_id),
    CONSTRAINT chk_agent_trace_sequence CHECK (sequence > 0),
    CONSTRAINT chk_agent_trace_attempt CHECK (attempt <= 1),
    CONSTRAINT chk_agent_trace_stage CHECK (
        stage IN (
            'RUN', 'DIALOGUE', 'RETRIEVAL', 'PLANNING', 'SQL_ADMISSION',
            'EXECUTION', 'VERIFICATION', 'REPAIR', 'SYNTHESIS'
        )
    ),
    CONSTRAINT chk_agent_trace_event_type CHECK (
        event_type IN (
            'RUN_RECEIVED', 'DIALOGUE_COMPLETED', 'RETRIEVAL_COMPLETED',
            'PLANNING_COMPLETED', 'SQL_ADMISSION_COMPLETED', 'EXECUTION_COMPLETED',
            'VERIFICATION_COMPLETED', 'REPAIR_COMPLETED', 'SYNTHESIS_COMPLETED',
            'RUN_TERMINATED'
        )
    ),
    CONSTRAINT chk_agent_trace_schema_version CHECK (schema_version = 'trace-event-v0.1'),
    CONSTRAINT chk_agent_trace_payload_fingerprint
        CHECK (payload_fingerprint REGEXP '^[0-9a-f]{64}$')
) ENGINE=InnoDB;
