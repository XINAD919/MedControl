-- Migration: adherence_analyses table
-- Stores the generated adherence score + LLM analysis per user

CREATE TABLE IF NOT EXISTS adherence_analyses (
    id          UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score       DECIMAL(3,1) NOT NULL CHECK (score >= 1.0 AND score <= 5.0),
    metrics     JSONB       NOT NULL DEFAULT '{}',
    llm_comment TEXT        NOT NULL,
    period_days INT         NOT NULL DEFAULT 30,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adherence_analyses_user_created
    ON adherence_analyses(user_id, created_at DESC);
