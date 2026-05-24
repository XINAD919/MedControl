-- ============================================================================
-- Migration: manual_reminder_sends
-- Rate-limit: máximo 1 recordatorio manual por dosis por caregiver.
-- ============================================================================

CREATE TABLE IF NOT EXISTS manual_reminder_sends (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reminder_id  VARCHAR(128) NOT NULL,
  caregiver_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  patient_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sent_at      TIMESTAMP DEFAULT NOW(),
  UNIQUE (reminder_id, caregiver_id)
);

CREATE INDEX IF NOT EXISTS idx_mrs_reminder   ON manual_reminder_sends(reminder_id);
CREATE INDEX IF NOT EXISTS idx_mrs_caregiver  ON manual_reminder_sends(caregiver_id);
