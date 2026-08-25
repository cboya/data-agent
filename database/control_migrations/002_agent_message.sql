CREATE TABLE IF NOT EXISTS agent_message (
    id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    sequence BIGINT UNSIGNED NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_agent_message_session_sequence (session_id, sequence),
    CONSTRAINT fk_agent_message_session
        FOREIGN KEY (session_id) REFERENCES agent_session (id),
    CONSTRAINT chk_agent_message_sequence CHECK (sequence > 0),
    CONSTRAINT chk_agent_message_role CHECK (role IN ('user', 'assistant'))
) ENGINE=InnoDB;
