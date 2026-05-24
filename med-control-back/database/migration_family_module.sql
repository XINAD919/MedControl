-- ============================================================================
-- Migration: family_invitations + family_members
-- ============================================================================

-- Table: family_invitations
-- Tracks all invitations sent by a USER (patient) to potential caregivers.
CREATE TABLE IF NOT EXISTS family_invitations (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  inviter_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  invited_email VARCHAR(255) NOT NULL,
  token         VARCHAR(128) NOT NULL UNIQUE,
  status        VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- Values: pending | accepted | rejected | expired
  expires_at    TIMESTAMP NOT NULL,
  created_at    TIMESTAMP DEFAULT NOW(),
  updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_invitations_inviter ON family_invitations(inviter_id);
CREATE INDEX IF NOT EXISTS idx_family_invitations_email   ON family_invitations(invited_email);

COMMENT ON COLUMN family_invitations.token IS
  'secrets.token_urlsafe(64) — used in accept/reject email links and as caregiver_token in /register';
COMMENT ON COLUMN family_invitations.status IS
  'pending | accepted | rejected | expired';

-- Auto-update updated_at
DROP TRIGGER IF EXISTS update_family_invitations_updated_at ON family_invitations;
CREATE TRIGGER update_family_invitations_updated_at
  BEFORE UPDATE ON family_invitations
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- Table: family_members
-- Represents an accepted caregiver<->patient link.
-- patient_id   = USER who owns the medical data
-- caregiver_id = CAREGIVER who has read-only access
CREATE TABLE IF NOT EXISTS family_members (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  caregiver_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   TIMESTAMP DEFAULT NOW(),
  UNIQUE (patient_id, caregiver_id)
);

CREATE INDEX IF NOT EXISTS idx_family_members_patient    ON family_members(patient_id);
CREATE INDEX IF NOT EXISTS idx_family_members_caregiver  ON family_members(caregiver_id);

COMMENT ON TABLE family_members IS
  'Accepted caregiver links. patient_id owns data, caregiver_id has read-only access.';
