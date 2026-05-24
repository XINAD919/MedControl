import type { Session } from 'next-auth'
import type { AdherenceAnalysis, Channel, ChannelType, Document, FamilyInvitation, FamilyMember, LinkedPatient, Reminder, ReminderNotification } from './types'
import { assertCanWrite } from './rbac'

const BASE_URL = '/api/backend'
const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000'

async function apiFetch<T>(path: string, accessToken: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ── Reminders ────────────────────────────────────────────────────────────────

export interface ReminderParams {
  status?: string
  date?: string
  medication?: string
}

export function fetchReminders(
  session: Session,
  params: ReminderParams = {},
): Promise<Reminder[]> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  if (params.date) qs.set('date', params.date)
  if (params.medication) qs.set('medication', params.medication)
  const query = qs.toString() ? `?${qs}` : ''
  return apiFetch<Reminder[]>(`/api/users/${session.user.id}/reminders${query}`, session.accessToken)
}

export function markReminderTaken(session: Session, reminderId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/api/users/${session.user.id}/reminders/${reminderId}/taken`,
    session.accessToken,
    { method: 'PATCH' },
  )
}

// ── Channels ─────────────────────────────────────────────────────────────────

export function fetchChannels(
  session: Session,
  verifiedOnly = false,
): Promise<Channel[]> {
  return apiFetch<Channel[]>(
    `/api/users/${session.user.id}/channels?verified_only=${verifiedOnly}`,
    session.accessToken,
  )
}

export interface ChannelConfig {
  channel: ChannelType
  notify_id: string
  is_primary?: boolean
  receive_reminders?: boolean
  metadata?: Record<string, unknown>
}

export function createChannel(session: Session, config: ChannelConfig): Promise<void> {
  assertCanWrite(session)
  return apiFetch<void>(`/api/users/${session.user.id}/channels`, session.accessToken, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
}

export function deleteChannel(session: Session, channel: ChannelType): Promise<void> {
  assertCanWrite(session)
  return apiFetch<void>(`/api/users/${session.user.id}/channels/${channel}`, session.accessToken, {
    method: 'DELETE',
  })
}

export function toggleChannelReminders(
  session: Session,
  channel: ChannelType,
): Promise<{ receive_reminders: boolean }> {
  assertCanWrite(session)
  return apiFetch<{ receive_reminders: boolean }>(
    `/api/users/${session.user.id}/channels/${channel}/toggle-reminders`,
    session.accessToken,
    { method: 'PATCH' },
  )
}

// ── Notifications ─────────────────────────────────────────────────────────────

export function fetchNotifications(
  session: Session,
  status?: string,
): Promise<ReminderNotification[]> {
  const qs = new URLSearchParams()
  if (status) qs.set('status', status)
  const query = qs.toString() ? `?${qs}` : ''
  return apiFetch<ReminderNotification[]>(
    `/api/users/${session.user.id}/notifications${query}`,
    session.accessToken,
  )
}

// ── Documents ─────────────────────────────────────────────────────────────────

export async function uploadDocument(session: Session, file: File): Promise<Document> {
  assertCanWrite(session)
  const formData = new FormData()
  formData.append('file', file)
  // Do NOT set Content-Type — browser must set it with the multipart boundary
  const res = await fetch(`${BASE_URL}/api/users/${session.user.id}/documents`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${session.accessToken}` },
    body: formData,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Document>
}

// ── Adherencia ────────────────────────────────────────────────────────────────

export function fetchLatestAdherenceAnalysis(session: Session): Promise<AdherenceAnalysis | null> {
  return apiFetch<AdherenceAnalysis | null>(
    `/api/users/${session.user.id}/adherence-analysis/latest`,
    session.accessToken,
  )
}

export function generateAdherenceAnalysis(
  session: Session,
  periodDays = 30,
): Promise<AdherenceAnalysis> {
  return apiFetch<AdherenceAnalysis>(
    `/api/users/${session.user.id}/adherence-analysis?period_days=${periodDays}`,
    session.accessToken,
    { method: 'POST' },
  )
}

// ── Familia ───────────────────────────────────────────────────────────────────

export function fetchFamilyMembers(session: Session): Promise<FamilyMember[]> {
  return apiFetch<FamilyMember[]>('/api/family/members', session.accessToken)
}

export function fetchLinkedPatients(session: Session): Promise<LinkedPatient[]> {
  return apiFetch<LinkedPatient[]>('/api/family/linked-patients', session.accessToken)
}

export function fetchFamilyInvitations(session: Session): Promise<FamilyInvitation[]> {
  return apiFetch<FamilyInvitation[]>('/api/family/invitations', session.accessToken)
}

export function inviteFamilyMember(session: Session, email: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>('/api/family/invite', session.accessToken, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
}

export function removeFamilyMember(session: Session, caregiverId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/api/family/members/${caregiverId}`,
    session.accessToken,
    { method: 'DELETE' },
  )
}

export function acceptInvitation(session: Session, token: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/api/family/accept/${token}`,
    session.accessToken,
    { method: 'POST' },
  )
}

export function rejectInvitation(session: Session, token: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/api/family/reject/${token}`,
    session.accessToken,
    { method: 'POST' },
  )
}

export function sendManualReminder(
  session: Session,
  patientId: string,
  reminderId: string,
): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/api/family/patients/${patientId}/reminders/${reminderId}/manual-reminder`,
    session.accessToken,
    { method: 'POST' },
  )
}

export function resendInvitation(session: Session, invitationId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/api/family/invitations/${invitationId}/resend`,
    session.accessToken,
    { method: 'POST' },
  )
}

export function revokeInvitation(session: Session, invitationId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/api/family/invitations/${invitationId}/revoke`,
    session.accessToken,
    { method: 'POST' },
  )
}

// ── WebSocket chat ────────────────────────────────────────────────────────────

export function connectChatSocket(
  session: Session,
  message: string,
  onToken: (token: string) => void,
  onDone: () => void,
  onError: () => void,
): void {
  const ws = new WebSocket(
    `${WS_URL}/ws/chat?session_id=${session.user.id}&token=${encodeURIComponent(session.accessToken)}`,
  )

  ws.onopen = () => {
    ws.send(JSON.stringify({ message }))
  }

  ws.onmessage = (event: MessageEvent<string>) => {
    onToken(event.data)
  }

  ws.onclose = () => {
    onDone()
  }

  ws.onerror = () => {
    onError()
    ws.close()
  }
}
