CREATE TABLE dim_region (
    id BIGINT UNSIGNED NOT NULL,
    province VARCHAR(64) NOT NULL,
    city VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dim_region_province_city (province, city)
) ENGINE=InnoDB;

CREATE TABLE dim_channel (
    id BIGINT UNSIGNED NOT NULL,
    code VARCHAR(32) NOT NULL,
    name VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dim_channel_code (code)
) ENGINE=InnoDB;

CREATE TABLE dim_category (
    id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dim_category_name (name)
) ENGINE=InnoDB;

CREATE TABLE dim_product (
    id BIGINT UNSIGNED NOT NULL,
    category_id BIGINT UNSIGNED NOT NULL,
    sku VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dim_product_sku (sku),
    KEY idx_dim_product_category (category_id),
    CONSTRAINT fk_product_category
        FOREIGN KEY (category_id) REFERENCES dim_category (id)
) ENGINE=InnoDB;

CREATE TABLE dim_user (
    id BIGINT UNSIGNED NOT NULL,
    region_id BIGINT UNSIGNED NOT NULL,
    channel_id BIGINT UNSIGNED NOT NULL,
    registered_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_dim_user_region (region_id),
    KEY idx_dim_user_channel (channel_id),
    CONSTRAINT fk_user_region
        FOREIGN KEY (region_id) REFERENCES dim_region (id),
    CONSTRAINT fk_user_channel
        FOREIGN KEY (channel_id) REFERENCES dim_channel (id)
) ENGINE=InnoDB;

CREATE TABLE fact_order (
    id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    channel_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(24) NOT NULL,
    total_amount DECIMAL(18, 2) NOT NULL,
    paid_amount DECIMAL(18, 2) NULL,
    created_at DATETIME(6) NOT NULL,
    paid_at DATETIME(6) NULL,
    completed_at DATETIME(6) NULL,
    PRIMARY KEY (id),
    KEY idx_order_user (user_id),
    KEY idx_order_channel (channel_id),
    KEY idx_order_created_at (created_at),
    KEY idx_order_paid_at (paid_at),
    CONSTRAINT fk_order_user
        FOREIGN KEY (user_id) REFERENCES dim_user (id),
    CONSTRAINT fk_order_channel
        FOREIGN KEY (channel_id) REFERENCES dim_channel (id),
    CONSTRAINT chk_order_amounts
        CHECK (total_amount >= 0 AND (paid_amount IS NULL OR paid_amount >= 0))
) ENGINE=InnoDB;

CREATE TABLE fact_order_item (
    id BIGINT UNSIGNED NOT NULL,
    order_id BIGINT UNSIGNED NOT NULL,
    product_id BIGINT UNSIGNED NOT NULL,
    quantity INT UNSIGNED NOT NULL,
    unit_price DECIMAL(18, 2) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_order_item_order (order_id),
    KEY idx_order_item_product (product_id),
    CONSTRAINT fk_order_item_order
        FOREIGN KEY (order_id) REFERENCES fact_order (id),
    CONSTRAINT fk_order_item_product
        FOREIGN KEY (product_id) REFERENCES dim_product (id),
    CONSTRAINT chk_order_item_values CHECK (quantity > 0 AND unit_price >= 0)
) ENGINE=InnoDB;

CREATE TABLE fact_payment_transaction (
    id BIGINT UNSIGNED NOT NULL,
    order_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(24) NOT NULL,
    amount DECIMAL(18, 2) NOT NULL,
    attempted_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_payment_order (order_id),
    KEY idx_payment_attempted_at (attempted_at),
    CONSTRAINT fk_payment_order
        FOREIGN KEY (order_id) REFERENCES fact_order (id),
    CONSTRAINT chk_payment_amount CHECK (amount >= 0)
) ENGINE=InnoDB;

CREATE TABLE fact_refund (
    id BIGINT UNSIGNED NOT NULL,
    order_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(24) NOT NULL,
    refund_amount DECIMAL(18, 2) NOT NULL,
    refunded_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_refund_order (order_id),
    KEY idx_refund_refunded_at (refunded_at),
    CONSTRAINT fk_refund_order
        FOREIGN KEY (order_id) REFERENCES fact_order (id),
    CONSTRAINT chk_refund_amount CHECK (refund_amount >= 0)
) ENGINE=InnoDB;

CREATE TABLE fact_user_event (
    id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    event_name VARCHAR(64) NOT NULL,
    occurred_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_user_event_user (user_id),
    KEY idx_user_event_occurred_at (occurred_at),
    CONSTRAINT fk_user_event_user
        FOREIGN KEY (user_id) REFERENCES dim_user (id)
) ENGINE=InnoDB;
