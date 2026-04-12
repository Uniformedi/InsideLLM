-- Migration: Create governance_settings_overrides table
-- Stores runtime configuration overrides (replaces .env file approach)

CREATE TABLE IF NOT EXISTS governance_settings_overrides (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL UNIQUE,
    value TEXT NOT NULL,
    updated_by VARCHAR(255) DEFAULT 'system',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- For MariaDB/MySQL (use AUTO_INCREMENT and DATETIME):
-- CREATE TABLE IF NOT EXISTS governance_settings_overrides (
--     id INT AUTO_INCREMENT PRIMARY KEY,
--     `key` VARCHAR(255) NOT NULL UNIQUE,
--     value TEXT NOT NULL,
--     updated_by VARCHAR(255) DEFAULT 'system',
--     updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
-- );
