-- ============================================================================
-- MedAI Database Initialization Script
-- ============================================================================
-- Este script crea todas las tablas, índices, tipos y funciones necesarias
-- para el sistema MedAI con soporte para:
-- - Gestión de usuarios multi-canal
-- - Recordatorios persistentes
-- - Documentos y RAG con pgvector
-- - Historial de conversaciones

-- ============================================================================
-- Extensions
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Custom Types (ENUMs)
-- ============================================================================

DO $$ BEGIN
  CREATE TYPE channel_type AS ENUM ('telegram', 'email', 'discord', 'webpush', 'sms');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE message_role AS ENUM ('system', 'user', 'assistant', 'tool');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE reminder_status AS ENUM ('scheduled', 'firing', 'completed', 'failed', 'cancelled');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE document_type AS ENUM ('prescription', 'medical_plan', 'lab_results', 'other');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

-- ============================================================================
-- Table: users
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username VARCHAR(100) UNIQUE NOT NULL,
  email VARCHAR(255),
  password_hash TEXT,
  role VARCHAR(20) DEFAULT 'USER',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  preferences JSONB DEFAULT '{}'::jsonb,
  active BOOLEAN DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email IS NOT NULL;

COMMENT ON TABLE users IS 'Usuarios del sistema MedAI';
COMMENT ON COLUMN users.preferences IS 'Configuración personalizada: idioma, zona horaria, etc.';

-- ============================================================================
-- Table: user_channels
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_channels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel channel_type NOT NULL,
  notify_id VARCHAR(500) NOT NULL,
  verified BOOLEAN DEFAULT false,
  is_primary BOOLEAN DEFAULT false,
  receive_reminders BOOLEAN DEFAULT true,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, channel)
);

CREATE INDEX IF NOT EXISTS idx_user_channels_user_id ON user_channels(user_id);
CREATE INDEX IF NOT EXISTS idx_user_channels_channel ON user_channels(channel);
CREATE INDEX IF NOT EXISTS idx_user_channels_verified ON user_channels(verified);

-- Migración segura para bases de datos existentes
DO $$ BEGIN
  ALTER TABLE user_channels ADD COLUMN receive_reminders BOOLEAN DEFAULT true;
EXCEPTION
  WHEN duplicate_column THEN null;
END $$;

COMMENT ON TABLE user_channels IS 'Canales de notificación configurados por cada usuario';
COMMENT ON COLUMN user_channels.notify_id IS 'ID específico del canal: chat_id (Telegram), email, Discord user_id, etc.';
COMMENT ON COLUMN user_channels.receive_reminders IS 'Si false, el canal no recibe recordatorios aunque esté verificado';
COMMENT ON COLUMN user_channels.metadata IS 'Datos extra: webhooks, tokens, player_ids, etc.';

-- ============================================================================
-- Table: sessions
-- ============================================================================

CREATE TABLE IF NOT EXISTS sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id VARCHAR(100) UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  last_message_at TIMESTAMP,
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_last_message ON sessions(last_message_at);

COMMENT ON TABLE sessions IS 'Sesiones de conversación con el agente';
COMMENT ON COLUMN sessions.session_id IS 'Identificador de sesión usado por Agent(session_id=...)';

-- ============================================================================
-- Table: messages
-- ============================================================================

CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role message_role NOT NULL,
  content TEXT NOT NULL,
  tool_calls JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  sequence_num INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_session_sequence ON messages(session_id, sequence_num);

COMMENT ON TABLE messages IS 'Mensajes individuales de cada sesión (reemplaza historial.json)';
COMMENT ON COLUMN messages.tool_calls IS 'Llamadas a tools cuando role = assistant';
COMMENT ON COLUMN messages.sequence_num IS 'Orden del mensaje en la conversación (0, 1, 2, ...)';

-- ============================================================================
-- Table: reminders
-- ============================================================================

CREATE TABLE IF NOT EXISTS reminders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reminder_id VARCHAR(100) NOT NULL,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,

  -- Datos del recordatorio
  medication VARCHAR(500) NOT NULL,
  schedule VARCHAR(100) NOT NULL,
  message TEXT NOT NULL,
  notes TEXT,

  -- Canal y destino
  channel channel_type NOT NULL,
  notify_id VARCHAR(500) NOT NULL,
  UNIQUE (reminder_id, channel),

  -- Timing
  scheduled_at TIMESTAMP NOT NULL,
  fired_at TIMESTAMP,
  completed_at TIMESTAMP,
  failed_at TIMESTAMP,

  -- Estado
  status reminder_status DEFAULT 'scheduled',
  error_message TEXT,

  -- Metadata
  metadata JSONB DEFAULT '{}'::jsonb,

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id);
CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);
CREATE INDEX IF NOT EXISTS idx_reminders_scheduled_at ON reminders(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_reminders_reminder_id ON reminders(reminder_id);
CREATE INDEX IF NOT EXISTS idx_reminders_session_id ON reminders(session_id);

COMMENT ON TABLE reminders IS 'Recordatorios creados por el agente (persistencia de n8n)';
COMMENT ON COLUMN reminders.metadata IS 'Datos extra de n8n, .ics generado, execution_id, etc.';

-- ============================================================================
-- Table: documents
-- ============================================================================

CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename VARCHAR(500) NOT NULL,
  file_type VARCHAR(50),
  document_type document_type DEFAULT 'other',
  file_path VARCHAR(1000),
  file_size INTEGER,

  -- Procesamiento
  extracted_text TEXT,
  processed BOOLEAN DEFAULT false,
  embeddings_generated BOOLEAN DEFAULT false,
  chunk_count INTEGER DEFAULT 0,

  metadata JSONB DEFAULT '{}'::jsonb,

  uploaded_at TIMESTAMP DEFAULT NOW(),
  processed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_processed ON documents(processed);
CREATE INDEX IF NOT EXISTS idx_documents_uploaded_at ON documents(uploaded_at);

COMMENT ON TABLE documents IS 'Documentos subidos por usuarios (recetas, planes de medicación)';
COMMENT ON COLUMN documents.metadata IS 'Fecha de prescripción, médico, farmacia, etc.';

-- ============================================================================
-- Table: document_embeddings
-- ============================================================================

CREATE TABLE IF NOT EXISTS document_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  chunk_text TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,

  embedding vector(512),  -- dimensión del modelo voyage-3-lite (Voyage AI)

  metadata JSONB DEFAULT '{}'::jsonb,

  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_document_id ON document_embeddings(document_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_user_id ON document_embeddings(user_id);

-- Índice de similitud vectorial (IVFFlat)
-- Solo crear si no existe (usar DROP INDEX IF EXISTS antes de crear si quieres recrear)
DO $$ BEGIN
  CREATE INDEX idx_embeddings_vector ON document_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
EXCEPTION
  WHEN duplicate_table THEN null;
END $$;

COMMENT ON TABLE document_embeddings IS 'Chunks y embeddings para RAG con búsqueda semántica';
COMMENT ON COLUMN document_embeddings.user_id IS 'Denormalizado para filtrar por usuario sin JOIN';
COMMENT ON COLUMN document_embeddings.metadata IS 'Página, sección, párrafo, etc.';

-- ============================================================================
-- Functions & Triggers
-- ============================================================================

-- Función para actualizar automáticamente updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers para updated_at
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_user_channels_updated_at ON user_channels;
CREATE TRIGGER update_user_channels_updated_at
  BEFORE UPDATE ON user_channels
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_sessions_updated_at ON sessions;
CREATE TRIGGER update_sessions_updated_at
  BEFORE UPDATE ON sessions
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_reminders_updated_at ON reminders;
CREATE TRIGGER update_reminders_updated_at
  BEFORE UPDATE ON reminders
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Data de prueba (opcional, comentar si no se necesita)
-- ============================================================================

-- Usuario de prueba
INSERT INTO users (id, username, email, preferences) VALUES
  ('11111111-1111-1111-1111-111111111111', 'daniel', 'daniel@example.com', '{"timezone": "Europe/Madrid", "language": "es"}'::jsonb)
ON CONFLICT (username) DO NOTHING;

-- Canales de prueba
INSERT INTO user_channels (user_id, channel, notify_id, verified, is_primary, receive_reminders, metadata) VALUES
  ('11111111-1111-1111-1111-111111111111', 'telegram', '123456789', true, true, true, '{}'::jsonb),
  ('11111111-1111-1111-1111-111111111111', 'email', 'daniel@example.com', true, false, true, '{}'::jsonb)
ON CONFLICT (user_id, channel) DO NOTHING;

-- Sesión de prueba
INSERT INTO sessions (id, user_id, session_id, metadata) VALUES
  ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'default', '{"provider": "anthropic", "model": "claude-sonnet-4-6"}'::jsonb)
ON CONFLICT (session_id) DO NOTHING;

-- ============================================================================
-- Views útiles
-- ============================================================================

-- Vista: recordatorios pendientes
CREATE OR REPLACE VIEW pending_reminders AS
SELECT
  r.reminder_id,
  r.user_id,
  u.username,
  r.medication,
  r.schedule,
  r.scheduled_at,
  r.channel,
  r.notify_id,
  EXTRACT(EPOCH FROM (r.scheduled_at - NOW())) / 60 AS minutes_until
FROM reminders r
JOIN users u ON u.id = r.user_id
WHERE r.status = 'scheduled'
  AND r.scheduled_at > NOW()
ORDER BY r.scheduled_at ASC;

COMMENT ON VIEW pending_reminders IS 'Recordatorios programados que aún no se han disparado';

-- Vista: historial de recordatorios del usuario
CREATE OR REPLACE VIEW user_reminders_history AS
SELECT
  r.user_id,
  u.username,
  r.reminder_id,
  r.medication,
  r.schedule,
  r.scheduled_at,
  r.fired_at,
  r.status,
  r.channel,
  CASE
    WHEN r.status = 'completed' THEN 'Enviado'
    WHEN r.status = 'failed' THEN 'Falló'
    WHEN r.status = 'cancelled' THEN 'Cancelado'
    WHEN r.status = 'firing' THEN 'Enviando...'
    ELSE 'Programado'
  END AS status_es
FROM reminders r
JOIN users u ON u.id = r.user_id
ORDER BY r.created_at DESC;

COMMENT ON VIEW user_reminders_history IS 'Historial completo de recordatorios por usuario';

-- ============================================================================
-- Stored Procedures útiles
-- ============================================================================

-- Función: obtener canales que deben recibir recordatorios
CREATE OR REPLACE FUNCTION get_notification_channels(p_user_id UUID)
RETURNS TABLE (
  channel channel_type,
  notify_id VARCHAR,
  metadata JSONB
) AS $$
BEGIN
  RETURN QUERY
  SELECT uc.channel, uc.notify_id, uc.metadata
  FROM user_channels uc
  WHERE uc.user_id = p_user_id
    AND uc.verified = true
    AND uc.receive_reminders = true
  ORDER BY uc.is_primary DESC, uc.created_at ASC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_notification_channels IS 'Canales verificados con receive_reminders=true (destinos de fan-out)';

-- Función: limpiar sesiones antiguas (más de 30 días sin actividad)
CREATE OR REPLACE FUNCTION cleanup_old_sessions()
RETURNS INTEGER AS $$
DECLARE
  deleted_count INTEGER;
BEGIN
  DELETE FROM sessions
  WHERE last_message_at < NOW() - INTERVAL '30 days'
    OR (last_message_at IS NULL AND created_at < NOW() - INTERVAL '30 days');

  GET DIAGNOSTICS deleted_count = ROW_COUNT;
  RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_sessions IS 'Elimina sesiones sin actividad en 30+ días';

-- ============================================================================
-- Grants (ajustar según tu usuario de aplicación)
-- ============================================================================

-- Si tienes un usuario específico para la aplicación, otorgar permisos:
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO medai_app;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO medai_app;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO medai_app;

-- ============================================================================
-- Recurrence support (migration segura para containers existentes)
-- ============================================================================

-- Auth: role column and unique email (migration-safe for existing containers)
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'USER';
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email) WHERE email IS NOT NULL;

ALTER TABLE reminders ADD COLUMN IF NOT EXISTS is_recurring        BOOLEAN   DEFAULT false;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS recurrence_type     VARCHAR(50);
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS recurrence_days     TEXT;       -- JSON array '[1,3,5]' (0=Dom…6=Sab)
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS recurrence_interval INTEGER   DEFAULT 1;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS recurrence_end_date TIMESTAMP;

ALTER TABLE reminders ADD COLUMN IF NOT EXISTS taken    BOOLEAN   DEFAULT false;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS taken_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_reminders_recurring
  ON reminders(is_recurring)
  WHERE is_recurring = true;

-- ============================================================================
-- Finalización
-- ============================================================================

-- Mostrar resumen
DO $$
DECLARE
  user_count INTEGER;
  session_count INTEGER;
  reminder_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO user_count FROM users;
  SELECT COUNT(*) INTO session_count FROM sessions;
  SELECT COUNT(*) INTO reminder_count FROM reminders;

  RAISE NOTICE '============================================';
  RAISE NOTICE 'MedAI Database Initialized Successfully';
  RAISE NOTICE '============================================';
  RAISE NOTICE 'Users: %', user_count;
  RAISE NOTICE 'Sessions: %', session_count;
  RAISE NOTICE 'Reminders: %', reminder_count;
  RAISE NOTICE '============================================';

END $$;


-- ============================================================================
-- Stored functions para Supabase SDK (rpc())
-- ============================================================================

CREATE OR REPLACE FUNCTION update_reminder_status(
    p_reminder_id TEXT,
    p_status TEXT,
    p_error_message TEXT DEFAULT NULL
) RETURNS VOID LANGUAGE sql AS $$
    UPDATE reminders SET
        status       = p_status::reminder_status,
        fired_at     = CASE WHEN p_status = 'firing'    THEN NOW() ELSE fired_at     END,
        completed_at = CASE WHEN p_status = 'completed' THEN NOW() ELSE completed_at END,
        failed_at    = CASE WHEN p_status = 'failed'    THEN NOW() ELSE failed_at    END,
        error_message = COALESCE(p_error_message, error_message)
    WHERE reminder_id = p_reminder_id;
$$;

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
        reminder_id,
        MIN(medication)::TEXT,
        MIN(schedule)::TEXT,
        MIN(message)::TEXT,
        MIN(notes)::TEXT,
        array_agg(channel::TEXT ORDER BY channel::TEXT),
        MIN(scheduled_at),
        MAX(fired_at),
        MIN(created_at),
        CASE
            WHEN bool_or(status = 'scheduled') THEN 'scheduled'
            WHEN bool_or(status = 'firing')    THEN 'firing'
            WHEN bool_or(status = 'failed')    THEN 'failed'
            WHEN bool_or(status = 'completed') THEN 'completed'
            ELSE 'cancelled'
        END,
        bool_or(taken),
        MAX(taken_at)
    FROM reminders
    WHERE user_id = p_user_id
      AND (p_status     IS NULL OR status = p_status::reminder_status)
      AND (p_date       IS NULL OR scheduled_at::date = p_date)
      AND (p_medication IS NULL OR medication ILIKE '%' || p_medication || '%')
    GROUP BY reminder_id
    ORDER BY MIN(scheduled_at) DESC
    LIMIT 100;
$$;

CREATE OR REPLACE FUNCTION search_similar_chunks(
    p_user_id   UUID,
    p_embedding FLOAT8[],
    p_top_k     INTEGER DEFAULT 3
) RETURNS TABLE (
    filename   TEXT,
    chunk_text TEXT,
    metadata   JSONB,
    distance   FLOAT8
) LANGUAGE sql STABLE AS $$
    SELECT
        d.filename::TEXT,
        de.chunk_text,
        de.metadata,
        (de.embedding <=> p_embedding::vector)::FLOAT8
    FROM document_embeddings de
    JOIN documents d ON d.id = de.document_id
    WHERE de.user_id = p_user_id
    ORDER BY de.embedding <=> p_embedding::vector
    LIMIT p_top_k;
$$;
