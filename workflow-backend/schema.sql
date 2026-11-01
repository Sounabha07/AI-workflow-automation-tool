-- ============================================================
-- DAG Engine Schema — rebuilt fresh for this project.
--
-- Fully idempotent: safe to call apply_schema() any number of times,
-- from the Dockerfile's CMD on every container start AND from
-- trigger.py. CREATE TYPE has no native IF NOT EXISTS, so it's wrapped
-- in a DO block that catches duplicate_object and no-ops instead.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$ BEGIN
    CREATE TYPE run_status_enum AS ENUM (
        'pending', 'running', 'succeeded', 'failed', 'waiting'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE run_type_enum AS ENUM (
        'production', 'test'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE block_execution_status_enum AS ENUM (
        'pending', 'ready', 'running', 'succeeded', 'failed', 'skipped', 'waiting'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS pipelines (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NULL,
    name            VARCHAR(255) NOT NULL,
    definition      JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id         UUID NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    status              run_status_enum NOT NULL DEFAULT 'pending',
    run_type            run_type_enum NOT NULL DEFAULT 'production',
    pipeline_snapshot   JSONB NOT NULL,
    total_blocks        INT NOT NULL DEFAULT 0,
    blocks_remaining    INT NOT NULL DEFAULT 0,
    error_summary       JSONB NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ NULL,
    finished_at         TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS block_executions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    block_id            TEXT NOT NULL,
    block_type          TEXT NOT NULL,
    status              block_execution_status_enum NOT NULL DEFAULT 'pending',
    remaining_deps      INT NOT NULL DEFAULT 0,
    retry_count         INT NOT NULL DEFAULT 0,
    is_retryable_error  BOOLEAN NULL,
    resolved_config     JSONB NULL,
    output              JSONB NULL,
    error               JSONB NULL,
    correlation_token   UUID NULL,
    wait_timeout_at     TIMESTAMPTZ NULL,
    started_at          TIMESTAMPTZ NULL,
    finished_at         TIMESTAMPTZ NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_run_block UNIQUE (run_id, block_id)
);

-- Saved secrets (e.g. a client's own LLM API key). secret_encrypted is a
-- Fernet token (app/credentials.py); the plaintext is never stored or
-- returned by the API. Blocks reference a credential by id.
CREATE TABLE IF NOT EXISTS credentials (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                VARCHAR(255) NOT NULL UNIQUE,
    type                TEXT NOT NULL,
    secret_encrypted    TEXT NOT NULL,
    hint                TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status);
CREATE INDEX IF NOT EXISTS idx_runs_pipeline_id ON runs (pipeline_id);
CREATE INDEX IF NOT EXISTS idx_block_executions_run_id ON block_executions (run_id);
CREATE INDEX IF NOT EXISTS idx_block_executions_status ON block_executions (status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_block_executions_correlation_token
    ON block_executions (correlation_token)
    WHERE correlation_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_block_executions_wait_timeout_at
    ON block_executions (wait_timeout_at)
    WHERE status = 'waiting';

ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS
    is_template BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE runs ADD COLUMN IF NOT EXISTS
    input_data JSONB NULL;

ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS
    is_active BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE runs ADD COLUMN IF NOT EXISTS
    seed_outputs JSONB NULL;

ALTER TABLE block_executions ADD COLUMN IF NOT EXISTS
    live_deps INT NOT NULL DEFAULT 0;

-- When the block last became 'ready' or was queued, so the sweeper can spot
-- one whose task never arrived. NULL on rows older than this column.
ALTER TABLE block_executions ADD COLUMN IF NOT EXISTS
    ready_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs (created_at DESC);

-- Deleting a pipeline deletes its whole run history: pipeline -> runs
-- (this FK) -> block_executions (already ON DELETE CASCADE). Existing
-- databases were created with ON DELETE RESTRICT; switch them only when
-- needed, so re-running this file doesn't rebuild the constraint.
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'runs_pipeline_id_fkey'
          AND conrelid = 'runs'::regclass
          AND confdeltype <> 'c'
    ) THEN
        ALTER TABLE runs DROP CONSTRAINT runs_pipeline_id_fkey;
        ALTER TABLE runs ADD CONSTRAINT runs_pipeline_id_fkey
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id) ON DELETE CASCADE;
    END IF;
END $$;

-- ============================================================
-- Wait-for-input blocks and schedule/webhook triggers.
-- ============================================================

-- A wait block whose run failed for another reason is cancelled, so a
-- later resume can tell "too late" (410) from "unknown token" (404).
-- ADD VALUE can't be used in the transaction that adds it, so nothing
-- below references 'cancelled'.
ALTER TYPE block_execution_status_enum ADD VALUE IF NOT EXISTS 'cancelled';

ALTER TABLE runs ADD COLUMN IF NOT EXISTS trigger_type TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS trigger_payload JSONB NULL;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS trigger_id UUID NULL;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS dedupe_key TEXT NULL;

-- A derived index of the schedule/webhook trigger blocks in each pipeline's
-- definition (which stays the source of truth). Rewritten by
-- app/triggers.py on pipeline create/update and activation; pipeline
-- delete cascades.
CREATE TABLE IF NOT EXISTS pipeline_triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id     UUID NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    block_id        TEXT NOT NULL,
    type            TEXT NOT NULL CHECK (type IN ('schedule', 'webhook')),
    webhook_token   TEXT UNIQUE,
    cron_expr       TEXT,
    timezone        TEXT,
    next_run_at     TIMESTAMPTZ,
    last_fired_at   TIMESTAMPTZ,
    UNIQUE (pipeline_id, block_id)
);

CREATE INDEX IF NOT EXISTS idx_triggers_due ON pipeline_triggers (next_run_at)
    WHERE type = 'schedule';

DO $$ BEGIN
    ALTER TABLE runs ADD CONSTRAINT runs_trigger_id_fkey
        FOREIGN KEY (trigger_id) REFERENCES pipeline_triggers(id) ON DELETE SET NULL;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- A webhook delivery id (X-GitHub-Delivery / Idempotency-Key) creates at
-- most one run per trigger.
CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_dedupe ON runs (trigger_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

-- Supersede the never-used correlation_token / wait_timeout_at columns
-- above, which are left in place so existing databases aren't rewritten.
ALTER TABLE block_executions ADD COLUMN IF NOT EXISTS resume_token TEXT UNIQUE;
ALTER TABLE block_executions ADD COLUMN IF NOT EXISTS wait_deadline TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_block_executions_wait_deadline
    ON block_executions (wait_deadline)
    WHERE status = 'waiting';

-- One fixed resume link per Wait for Input block, shown after the workflow
-- is saved (like a webhook URL). POSTing to it resumes the run that has
-- waited longest at that block. Synced with the definition by
-- engine/triggers.py; the token survives saves; pipeline delete cascades.
CREATE TABLE IF NOT EXISTS pipeline_wait_links (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id     UUID NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    block_id        TEXT NOT NULL,
    token           TEXT NOT NULL UNIQUE,
    UNIQUE (pipeline_id, block_id)
);
