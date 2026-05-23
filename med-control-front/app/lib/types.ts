export type ReminderStatus = 'scheduled' | 'firing' | 'completed' | 'failed' | 'cancelled'
export type ChannelType = 'telegram' | 'email' | 'discord' | 'webpush' | 'whatsapp' | 'sms'

export interface Reminder {
  reminder_id: string
  medication: string
  schedule: string
  message: string
  notes: string | null
  channels: ChannelType[]
  scheduled_at: string
  fired_at: string | null
  status: ReminderStatus
  created_at: string
  taken: boolean
  taken_at: string | null
}

export interface Channel {
  channel: ChannelType
  notify_id: string
  verified: boolean
  is_primary: boolean
  receive_reminders: boolean
  metadata: Record<string, unknown>
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  document_id?: string
}

export interface Document {
  id: string
  filename: string
  file_type: string | null
  document_type: string
  file_size: number | null
  processed: boolean
  chunk_count: number
  uploaded_at: string
  processing?: boolean
}

export type UploadStatus = 'idle' | 'uploading' | 'success' | 'error'

export interface AdherenceMetrics {
  total_due: number
  total_taken: number
  adherence_rate: number
  punctuality_rate: number
  avg_delay_minutes: number
  recent_adherence_rate: number
  medications: string[]
  trend: 'mejorando' | 'estable' | 'empeorando'
}

export interface AdherenceAnalysis {
  id: string
  score: number
  metrics: AdherenceMetrics
  llm_comment: string
  period_days: number
  created_at: string
}

export interface ReminderNotification {
  id: string
  reminder_id: string
  channel: ChannelType
  notify_id: string
  status: ReminderStatus
  fired_at: string | null
  completed_at: string | null
  failed_at: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  medication: string | null
  scheduled_at: string | null
}
