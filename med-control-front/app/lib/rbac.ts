import type { Session } from 'next-auth'

export type UserRole = 'USER' | 'CAREGIVER'

export function isCaregiver(session: Session | null): boolean {
  return (session?.user?.linkedPatientIds?.length ?? 0) > 0
}

export function canWrite(session: Session | null): boolean {
  return !!session?.user?.id
}

export function assertCanWrite(session: Session | null): void {
  if (!canWrite(session)) {
    throw new Error('No tienes permiso para realizar esta acción.')
  }
}
