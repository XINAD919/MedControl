-- Migra columnas TIMESTAMP (naive) a TIMESTAMPTZ en reminders y reminder_notifications.
-- Los valores almacenados estaban en UTC, por eso se usa AT TIME ZONE 'UTC' en el USING.
--
-- Ejecutar con:
--   psql -U postgres -d postgres -f database/migration_timestamptz.sql

-- 1. Bajar vistas que dependen de las columnas a alterar
DROP VIEW IF EXISTS user_reminders_history;
DROP VIEW IF EXISTS pending_reminders;

-- 2. Alterar tablas
ALTER TABLE reminders
  ALTER COLUMN scheduled_at        TYPE TIMESTAMPTZ USING scheduled_at AT TIME ZONE 'UTC',
  ALTER COLUMN recurrence_end_date TYPE TIMESTAMPTZ USING recurrence_end_date AT TIME ZONE 'UTC',
  ALTER COLUMN created_at          TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at          TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC';

ALTER TABLE reminder_notifications
  ALTER COLUMN fired_at     TYPE TIMESTAMPTZ USING fired_at AT TIME ZONE 'UTC',
  ALTER COLUMN completed_at TYPE TIMESTAMPTZ USING completed_at AT TIME ZONE 'UTC',
  ALTER COLUMN failed_at    TYPE TIMESTAMPTZ USING failed_at AT TIME ZONE 'UTC',
  ALTER COLUMN created_at   TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at   TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC';

-- 3. Recrear las vistas (definición idéntica a init.sql)
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

COMMENT ON VIEW pending_reminders IS 'Recordatorios programados que aún no se han disparado';

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

COMMENT ON VIEW user_reminders_history IS 'Historial completo de recordatorios por usuario';
