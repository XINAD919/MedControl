-- ============================================================================
-- Migration: dual-role support
-- El rol caregiver ahora se determina por la tabla family_members,
-- no por el campo role en users. Todos los usuarios son USER.
-- ============================================================================

UPDATE users SET role = 'USER' WHERE role = 'CAREGIVER';
