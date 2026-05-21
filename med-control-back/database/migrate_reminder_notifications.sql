-- ============================================================================
-- Migration: reminder_notifications
--
-- Separa la entrega por canal (fan-out) del recordatorio en sí.
-- Antes: reminders tiene 1 fila por canal  (UNIQUE reminder_id, channel)
-- Después: reminders tiene 1 fila por reminder_id
--          reminder_notifications tiene 1 fila por canal
-- ============================================================================

BEGIN;

-- ── 1. Tabla reminder_notifications ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS reminder_notifications (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reminder_id VARCHAR(100) NOT NULL,
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel     channel_type NOT NULL,
  notify_id   VARCHAR(500) NOT NULL,

  status        reminder_status DEFAULT 'scheduled',
  fired_at      TIMESTAMP,
  completed_at  TIMESTAMP,
  failed_at     TIMESTAMP,
  error_message TEXT,

  metadata   JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),

  UNIQUE (reminder_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_rn_reminder_id ON reminder_notifications(reminder_id);
CREATE INDEX IF NOT EXISTS idx_rn_user_id     ON reminder_notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_rn_status      ON reminder_notifications(status);

DROP TRIGGER IF EXISTS update_reminder_notifications_updated_at ON reminder_notifications;
CREATE TRIGGER update_reminder_notifications_updated_at
  BEFORE UPDATE ON reminder_notifications
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE reminder_notifications IS
  'Entrega de un recordatorio por canal (fan-out). Una fila por (reminder_id, channel).';

-- ── 2. Migrar datos existentes ───────────────────────────────────────────────
-- Copiar cada fila de reminders (que tiene channel+notify_id) a reminder_notifications.

INSERT INTO reminder_notifications (
  reminder_id, user_id, channel, notify_id,
  status, fired_at, completed_at, failed_at, error_message,
  metadata, created_at
)
SELECT DISTINCT ON (reminder_id, channel)
  reminder_id,
  user_id,
  channel,
  notify_id,
  status,
  fired_at,
  completed_at,
  failed_at,
  error_message,
  COALESCE(metadata, '{}'::jsonb),
  created_at
FROM reminders
ORDER BY reminder_id, channel, created_at
ON CONFLICT (reminder_id, channel) DO NOTHING;

-- ── 3. Deduplicar reminders: conservar una sola fila por reminder_id ─────────
-- Usamos ROW_NUMBER para identificar la fila más antigua por reminder_id.

WITH ranked AS (
  SELECT id,
         ROW_NUMBER() OVER (PARTITION BY reminder_id ORDER BY created_at ASC) AS rn
  FROM reminders
)
DELETE FROM reminders
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- ── 4. Eliminar vistas dependientes y columnas de entrega de reminders ───────
-- Las vistas usan channel/notify_id/fired_at; las recreamos más abajo.

DROP VIEW IF EXISTS pending_reminders;
DROP VIEW IF EXISTS user_reminders_history;

ALTER TABLE reminders DROP COLUMN IF EXISTS channel;
ALTER TABLE reminders DROP COLUMN IF EXISTS notify_id;
ALTER TABLE reminders DROP COLUMN IF EXISTS fired_at;
ALTER TABLE reminders DROP COLUMN IF EXISTS completed_at;
ALTER TABLE reminders DROP COLUMN IF EXISTS failed_at;
ALTER TABLE reminders DROP COLUMN IF EXISTS error_message;

-- ── 4b. Recrear vistas con el nuevo schema ───────────────────────────────────

CREATE OR REPLACE VIEW pending_reminders AS
SELECT
  r.reminder_id,
  r.user_id,
  u.username,
  r.medication,
  r.schedule,
  r.scheduled_at,
  rn.channel,
  rn.notify_id,
  EXTRACT(EPOCH FROM (r.scheduled_at - NOW())) / 60 AS minutes_until
FROM reminders r
JOIN users u ON u.id = r.user_id
LEFT JOIN reminder_notifications rn ON rn.reminder_id = r.reminder_id
WHERE r.status = 'scheduled'
  AND r.scheduled_at > NOW()
ORDER BY r.scheduled_at ASC;

CREATE OR REPLACE VIEW user_reminders_history AS
SELECT
  r.user_id,
  u.username,
  r.reminder_id,
  r.medication,
  r.schedule,
  r.scheduled_at,
  MAX(rn.fired_at) AS fired_at,
  r.status,
  array_agg(rn.channel ORDER BY rn.channel) AS channels,
  CASE
    WHEN r.status = 'completed' THEN 'Enviado'
    WHEN r.status = 'failed'    THEN 'Falló'
    WHEN r.status = 'cancelled' THEN 'Cancelado'
    WHEN r.status = 'firing'    THEN 'Enviando...'
    ELSE 'Programado'
  END AS status_es
FROM reminders r
JOIN users u ON u.id = r.user_id
LEFT JOIN reminder_notifications rn ON rn.reminder_id = r.reminder_id
GROUP BY r.user_id, u.username, r.reminder_id, r.medication, r.schedule,
         r.scheduled_at, r.status, r.created_at
ORDER BY r.created_at DESC;

-- ── 5. Restricción de unicidad: reminder_id es ahora clave natural ───────────

ALTER TABLE reminders DROP CONSTRAINT IF EXISTS reminders_reminder_id_channel_key;
ALTER TABLE reminders ADD CONSTRAINT reminders_reminder_id_key UNIQUE (reminder_id);

-- ── 6. FK desde reminder_notifications → reminders ───────────────────────────
-- Permite a PostgREST hacer embedded queries y garantiza integridad.

ALTER TABLE reminder_notifications
  ADD CONSTRAINT fk_rn_reminder_id
  FOREIGN KEY (reminder_id) REFERENCES reminders(reminder_id)
  ON DELETE CASCADE;

-- ── 7. Actualizar función update_reminder_status ─────────────────────────────
-- Ahora actualiza reminder_notifications Y el estado agregado en reminders.

CREATE OR REPLACE FUNCTION update_reminder_status(
    p_reminder_id   TEXT,
    p_status        TEXT,
    p_error_message TEXT DEFAULT NULL
) RETURNS VOID LANGUAGE sql AS $$
    UPDATE reminder_notifications SET
        status        = p_status::reminder_status,
        fired_at      = CASE WHEN p_status = 'firing'    THEN NOW() ELSE fired_at     END,
        completed_at  = CASE WHEN p_status = 'completed' THEN NOW() ELSE completed_at END,
        failed_at     = CASE WHEN p_status = 'failed'    THEN NOW() ELSE failed_at    END,
        error_message = COALESCE(p_error_message, error_message),
        updated_at    = NOW()
    WHERE reminder_id = p_reminder_id;

    UPDATE reminders SET
        status     = p_status::reminder_status,
        updated_at = NOW()
    WHERE reminder_id = p_reminder_id;
$$;

-- ── 8. Actualizar función get_user_reminders_grouped ─────────────────────────
-- Ahora reminders tiene 1 sola fila; se hace JOIN con reminder_notifications
-- para obtener el array de canales y el fired_at más reciente.

CREATE OR REPLACE FUNCTION get_user_reminders_grouped(
    p_user_id    UUID,
    p_status     TEXT DEFAULT NULL,
    p_date       DATE DEFAULT NULL,
    p_medication TEXT DEFAULT NULL
) RETURNS TABLE (
    reminder_id  TEXT,
    medication   TEXT,
    schedule     TEXT,
    message      TEXT,
    notes        TEXT,
    channels     TEXT[],
    scheduled_at TIMESTAMPTZ,
    fired_at     TIMESTAMPTZ,
    created_at   TIMESTAMPTZ,
    status       TEXT,
    taken        BOOLEAN,
    taken_at     TIMESTAMPTZ
) LANGUAGE sql STABLE AS $$
    SELECT
        r.reminder_id,
        r.medication,
        r.schedule,
        r.message,
        r.notes,
        COALESCE(
            array_agg(rn.channel::TEXT ORDER BY rn.channel::TEXT)
              FILTER (WHERE rn.channel IS NOT NULL),
            '{}'::TEXT[]
        ),
        r.scheduled_at,
        MAX(rn.fired_at),
        r.created_at,
        r.status::TEXT,
        r.taken,
        r.taken_at
    FROM reminders r
    LEFT JOIN reminder_notifications rn ON rn.reminder_id = r.reminder_id
    WHERE r.user_id = p_user_id
      AND (p_status     IS NULL OR r.status = p_status::reminder_status)
      AND (p_date       IS NULL OR r.scheduled_at::date = p_date)
      AND (p_medication IS NULL OR r.medication ILIKE '%' || p_medication || '%')
    GROUP BY
        r.reminder_id, r.medication, r.schedule, r.message, r.notes,
        r.scheduled_at, r.created_at, r.status, r.taken, r.taken_at
    ORDER BY r.scheduled_at DESC
    LIMIT 100;
$$;

COMMIT;
