-- ============================================================================
-- Migration: is_private flag on reminders
-- Permite al usuario marcar un medicamento/tratamiento como privado
-- para que sus caregivers no lo vean.
-- ============================================================================

ALTER TABLE reminders
  ADD COLUMN IF NOT EXISTS is_private BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_reminders_is_private ON reminders(user_id, is_private);
