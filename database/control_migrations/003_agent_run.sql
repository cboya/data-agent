CREATE TABLE IF NOT EXISTS agent_run (
    id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    repair_count INT UNSIGNED NOT NULL DEFAULT 0,
    started_at DATETIME(6) NOT NULL,
    completed_at DATETIME(6) NULL,
    error_code VARCHAR(128) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_agent_run_id_session (id, session_id),
    KEY idx_agent_run_session_started (session_id, started_at),
    CONSTRAINT fk_agent_run_session
        FOREIGN KEY (session_id) REFERENCES agent_session (id),
    CONSTRAINT chk_agent_run_status CHECK (
        status IN (
            'RECEIVED', 'UNDERSTANDING', 'CLARIFYING', 'RETRIEVING', 'PLANNING',
            'VALIDATING', 'EXECUTING', 'VERIFYING', 'SYNTHESIZING', 'COMPLETED',
            'POLICY_DENIED', 'QUERY_TOO_EXPENSIVE', 'REPAIR_EXHAUSTED', 'FAILED'
        )
    ),
    CONSTRAINT chk_agent_run_terminal_time CHECK (
        (
            status IN (
                'CLARIFYING', 'COMPLETED', 'POLICY_DENIED', 'QUERY_TOO_EXPENSIVE',
                'REPAIR_EXHAUSTED', 'FAILED'
            )
            AND completed_at IS NOT NULL
        )
        OR
        (
            status NOT IN (
                'CLARIFYING', 'COMPLETED', 'POLICY_DENIED', 'QUERY_TOO_EXPENSIVE',
                'REPAIR_EXHAUSTED', 'FAILED'
            )
            AND completed_at IS NULL
        )
    ),
    CONSTRAINT chk_agent_run_timestamps
        CHECK (completed_at IS NULL OR completed_at >= started_at)
) ENGINE=InnoDB;
