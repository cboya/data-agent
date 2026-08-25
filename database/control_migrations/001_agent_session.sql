CREATE TABLE IF NOT EXISTS agent_session (
    id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    requirement_json JSON NOT NULL,
    revision BIGINT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT chk_agent_session_status
        CHECK (status IN ('ACTIVE', 'COMPLETED', 'FAILED')),
    CONSTRAINT chk_agent_session_timestamps
        CHECK (updated_at >= created_at)
) ENGINE=InnoDB;
