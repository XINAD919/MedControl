'use client'

import { useEffect, useMemo, useState } from 'react'
import { useSession } from 'next-auth/react'
import { fetchNotifications } from '../lib/api'
import type { ReminderNotification, ReminderStatus, ChannelType } from '../lib/types'
import { Bell, Mail, Send, Globe, Phone, Hash, MessageCircle, Clock, AlertCircle, CheckCircle, Loader } from 'lucide-react'

const STATUS_CLASSES: Record<ReminderStatus, string> = {
  scheduled: 'bg-blue-100 text-blue-600',
  firing:    'bg-yellow-100 text-yellow-700',
  completed: 'bg-green-100 text-green-700',
  failed:    'bg-red-100 text-red-600',
  cancelled: 'bg-gray-100 text-gray-500',
}

const STATUS_LABELS: Record<ReminderStatus, string> = {
  scheduled: 'Programado',
  firing:    'Enviando',
  completed: 'Enviado',
  failed:    'Fallido',
  cancelled: 'Cancelado',
}

const CHANNEL_ICONS: Record<string, React.ReactNode> = {
  telegram: <Send size={13} />,
  email:    <Mail size={13} />,
  discord:  <Hash size={13} />,
  webpush:  <Globe size={13} />,
  sms:      <Phone size={13} />,
  whatsapp: <MessageCircle size={13} />,
}

const CHANNEL_LABELS: Record<string, string> = {
  telegram: 'Telegram',
  email:    'Email',
  discord:  'Discord',
  webpush:  'Web Push',
  sms:      'SMS',
  whatsapp: 'WhatsApp',
}

const CHANNEL_COLORS: Record<string, string> = {
  telegram: 'bg-sky-50 text-sky-600 border-sky-100',
  email:    'bg-purple-50 text-purple-600 border-purple-100',
  discord:  'bg-indigo-50 text-indigo-600 border-indigo-100',
  webpush:  'bg-orange-50 text-orange-600 border-orange-100',
  sms:      'bg-teal-50 text-teal-600 border-teal-100',
  whatsapp: 'bg-green-50 text-green-600 border-green-100',
}

type FilterStatus = 'all' | ReminderStatus
type FilterChannel = 'all' | ChannelType

const STATUS_FILTERS: { value: FilterStatus; label: string }[] = [
  { value: 'all',       label: 'Todos' },
  { value: 'scheduled', label: 'Programados' },
  { value: 'firing',    label: 'Enviando' },
  { value: 'completed', label: 'Enviados' },
  { value: 'failed',    label: 'Fallidos' },
  { value: 'cancelled', label: 'Cancelados' },
]

const CHANNEL_FILTERS: { value: FilterChannel; label: string }[] = [
  { value: 'all',      label: 'Todos los canales' },
  { value: 'telegram', label: 'Telegram' },
  { value: 'email',    label: 'Email' },
  { value: 'discord',  label: 'Discord' },
  { value: 'webpush',  label: 'Web Push' },
  { value: 'sms',      label: 'SMS' },
]

function toUtcDate(iso: string): Date {
  const hasOffset = /([+-]\d{2}:\d{2}|Z)$/.test(iso)
  return new Date(hasOffset ? iso : iso + 'Z')
}

function formatDateTime(iso: string | null) {
  if (!iso) return null
  return toUtcDate(iso).toLocaleString('es-ES', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export default function NotificationsPage() {
  const { data: session, status } = useSession()
  const [notifications, setNotifications] = useState<ReminderNotification[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all')
  const [filterChannel, setFilterChannel] = useState<FilterChannel>('all')

  useEffect(() => {
    if (!session) return
    fetchNotifications(session)
      .then(setNotifications)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [session])

  const filtered = useMemo(() => {
    return notifications.filter(n => {
      if (filterStatus !== 'all' && n.status !== filterStatus) return false
      if (filterChannel !== 'all' && n.channel !== filterChannel) return false
      return true
    })
  }, [notifications, filterStatus, filterChannel])

  if (status === 'loading') return <div className="p-6 animate-pulse"><div className="h-6 bg-white rounded w-48" /></div>
  if (!session) return null

  return (
    <div className="p-4 sm:p-6 pt-16 sm:pt-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-800">Notificaciones</h1>
        <p className="text-sm text-gray-400 mt-0.5">Historial de entregas por canal</p>
      </div>

      {/* Filtros */}
      <div className="flex flex-col gap-3 mb-6">
        <div className="flex gap-2 flex-wrap">
          {STATUS_FILTERS.map(f => (
            <button
              key={f.value}
              type="button"
              onClick={() => setFilterStatus(f.value)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                filterStatus === f.value
                  ? 'bg-blue-500 text-white'
                  : 'bg-white text-gray-600 border border-gray-200 hover:border-blue-300'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2 flex-wrap">
          {CHANNEL_FILTERS.map(f => (
            <button
              key={f.value}
              type="button"
              onClick={() => setFilterChannel(f.value)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                filterChannel === f.value
                  ? 'bg-gray-700 text-white'
                  : 'bg-white text-gray-500 border border-gray-200 hover:border-gray-400'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 text-red-600 text-sm rounded-xl border border-red-100">
          Error al cargar notificaciones: {error}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="animate-pulse h-20 bg-white rounded-xl border border-blue-50" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-white rounded-2xl p-10 text-center border border-blue-50">
          <Bell size={36} className="text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-gray-400">No hay notificaciones</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map(n => (
            <div
              key={n.id}
              className="bg-white rounded-xl px-4 py-3 border border-blue-50 shadow-sm flex items-start gap-4"
            >
              {/* Estado icon */}
              <div className="shrink-0 mt-0.5">
                {n.status === 'completed' && <CheckCircle size={16} className="text-green-400" />}
                {n.status === 'failed'    && <AlertCircle size={16} className="text-red-400" />}
                {n.status === 'firing'    && <Loader size={16} className="text-yellow-400 animate-spin" />}
                {(n.status === 'scheduled' || n.status === 'cancelled') && (
                  <Clock size={16} className="text-gray-300" />
                )}
              </div>

              {/* Contenido */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold text-gray-800 truncate">
                    {n.medication ?? n.reminder_id}
                  </span>
                  <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border font-medium ${CHANNEL_COLORS[n.channel] ?? 'bg-gray-50 text-gray-500 border-gray-100'}`}>
                    {CHANNEL_ICONS[n.channel] ?? <Bell size={13} />}
                    {CHANNEL_LABELS[n.channel] ?? n.channel}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_CLASSES[n.status]}`}>
                    {STATUS_LABELS[n.status]}
                  </span>
                </div>

                <div className="flex items-center gap-4 mt-1 flex-wrap">
                  {n.scheduled_at && (
                    <span className="text-xs text-gray-400">
                      Programado: {formatDateTime(n.scheduled_at)}
                    </span>
                  )}
                  {n.fired_at && (
                    <span className="text-xs text-gray-400">
                      Enviado: {formatDateTime(n.fired_at)}
                    </span>
                  )}
                  {n.failed_at && (
                    <span className="text-xs text-red-400">
                      Falló: {formatDateTime(n.failed_at)}
                    </span>
                  )}
                </div>

                {n.error_message && (
                  <p className="text-xs text-red-500 mt-1 truncate">{n.error_message}</p>
                )}
              </div>

              {/* Timestamp de creación */}
              <div className="shrink-0 text-right hidden sm:block">
                <span className="text-xs text-gray-300">
                  {formatDateTime(n.created_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
