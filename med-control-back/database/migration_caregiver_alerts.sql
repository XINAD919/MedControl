-- ============================================================================
-- Migration: caregiver_missed_dose_alerts
-- Registra qué alertas de dosis omitida ya se enviaron, para evitar duplicados.
-- ============================================================================

CREATE TABLE IF NOT EXISTS caregiver_missed_dose_alerts (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reminder_id  VARCHAR(128) NOT NULL,
  caregiver_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sent_at      TIMESTAMP DEFAULT NOW(),
  UNIQUE (reminder_id, caregiver_id)
);

CREATE INDEX IF NOT EXISTS idx_cma_reminder ON caregiver_missed_dose_alerts(reminder_id);
CREATE INDEX IF NOT EXISTS idx_cma_caregiver ON caregiver_missed_dose_alerts(caregiver_id);
