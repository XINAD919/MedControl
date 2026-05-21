import type { Session } from 'next-auth'
import type { Channel, ChannelType, Document, Reminder } from './types'
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
