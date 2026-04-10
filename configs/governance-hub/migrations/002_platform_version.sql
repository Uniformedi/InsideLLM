-- Migration: Add platform_version column to fleet tables
-- Tracks which InsideLLM version each instance is running

-- PostgreSQL / MariaDB compatible
ALTER TABLE governance_instances ADD COLUMN IF NOT EXISTS platform_version VARCHAR(20) DEFAULT 'unknown';
ALTER TABLE governance_telemetry ADD COLUMN IF NOT EXISTS platform_version VARCHAR(20) DEFAULT 'unknown';

-- For MSSQL (run manually if using SQL Server):
-- IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('governance_instances') AND name = 'platform_version')
--   ALTER TABLE governance_instances ADD platform_version VARCHAR(20) DEFAULT 'unknown';
-- IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('governance_telemetry') AND name = 'platform_version')
--   ALTER TABLE governance_telemetry ADD platform_version VARCHAR(20) DEFAULT 'unknown';
