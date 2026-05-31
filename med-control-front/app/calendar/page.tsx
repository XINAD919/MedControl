'use client'

import { useEffect, useMemo, useState } from 'react'
import { useSession } from 'next-auth/react'
import { fetchReminders, markReminderTaken } from '../lib/api'
import type { Reminder, ReminderStatus } from '../lib/types'
import { CalendarDays, Check, Clock, Pill, AlertTriangle } from 'lucide-react'

const STATUS_CLASSES: Record<ReminderStatus, string> = {
  scheduled: 'bg-blue-100 text-blue-600',
  firing: 'bg-yellow-100 text-yellow-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-600',
  cancelled: 'bg-gray-100 text-gray-500',
}

const STATUS_LABELS: Record<ReminderStatus, string> = {
  scheduled: 'Programado',
  firing: 'Enviando',
  completed: 'Enviado',
  failed: 'Fallido',
  cancelled: 'Cancelado',
}

type FilterOption = 'all' | 'scheduled'

const FILTERS: { value: FilterOption; label: string }[] = [
  { value: 'all',       label: 'Todos' },
  { value: 'scheduled', label: 'Programados' },
]

function formatDate(dateStr: string) {
  const [year, month, day] = dateStr.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString('es-ES', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function toUtcDate(iso: string): Date {
  // Treat bare datetime strings (no timezone suffix) as UTC
  const hasOffset = /([+-]\d{2}:\d{2}|Z)$/.test(iso)
  return new Date(hasOffset ? iso : iso + 'Z')
}

function canMarkTaken(scheduledAt: string): boolean {
  return toUtcDate(scheduledAt).getTime() - Date.now() < 2 * 60 * 60 * 1000
}

function formatTime(iso: string) {
  return toUtcDate(iso).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', hour12: true })
}

function formatShortDate(iso: string) {
  return toUtcDate(iso).toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' })
}

function localDateKey(iso: string): string {
  // Returns YYYY-MM-DD in the user's local timezone
  const d = toUtcDate(iso)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export default function CalendarPage() {
  const { data: session, status } = useSession()
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterOption>('all')
  const [search, setSearch] = useState('')

  useEffect(() => {
    if (!session) return
    fetchReminders(session)
      .then(setReminders)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [session])

  function handleTaken(reminderId: string) {
    if (!session) return
    markReminderTaken(session, reminderId).then(() => {
      setReminders(prev => prev.map(r =>
        r.reminder_id === reminderId ? { ...r, taken: true, taken_at: new Date().toISOString() } : r
      ))
    }).catch(() => {})
  }

  const grouped = useMemo(() => {
    const filtered = reminders.filter(r =>
      (filter === 'all' || r.status === filter) &&
      (!search || r.medication.toLowerCase().includes(search.toLowerCase()))
    )

    const map: Record<string, Reminder[]> = {}
    for (const r of filtered) {
      const date = localDateKey(r.scheduled_at)
      if (!map[date]) map[date] = []
      map[date].push(r)
    }
    const sortedDates = Object.keys(map).sort()
    return sortedDates.map(date => ({ date, reminders: map[date] }))
  }, [reminders, filter, search])

  if (status === 'loading') return <div className="p-6 animate-pulse"><div className="h-6 bg-white rounded w-48" /></div>
  if (!session) return null

  return (
    <div className="p-4 sm:p-6 pt-16 sm:pt-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-800">Calendario</h1>
        <p className="text-sm text-gray-400 mt-0.5">Agenda de recordatorios</p>
      </div>

      {/* Filtros */}
      <div className="flex flex-col gap-3 mb-6">
        <div className="flex gap-2 flex-wrap">
          {FILTERS.map(f => (
            <button
              key={f.value}
              type="button"
              onClick={() => setFilter(f.value)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                filter === f.value
                  ? 'bg-blue-500 text-white'
                  : 'bg-white text-gray-600 border border-gray-200 hover:border-blue-300'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          aria-label="Buscar medicamento"
          placeholder="Buscar medicamento…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="w-full bg-white border border-gray-200 rounded-xl px-4 py-2 text-sm text-gray-700 placeholder-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 text-red-600 text-sm rounded-xl border border-red-100">
          Error al cargar recordatorios: {error}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col gap-6">
          {[0, 1].map(i => (
            <div key={i} className="animate-pulse">
              <div className="h-4 bg-gray-100 rounded w-48 mb-3" />
              <div className="flex flex-col gap-2">
                <div className="h-14 bg-white rounded-xl border border-blue-50" />
                <div className="h-14 bg-white rounded-xl border border-blue-50" />
              </div>
            </div>
          ))}
        </div>
      ) : grouped.length === 0 ? (
        <div className="bg-white rounded-2xl p-10 text-center border border-blue-50">
          <CalendarDays size={36} className="text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-gray-400">No se encontraron recordatorios</p>
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          {grouped.map(({ date, reminders: dayReminders }) => (
            <div key={date}>
              <h2 className="text-xs font-semibold text-gray-400 tracking-wider mb-3 capitalize">
                {formatDate(date)}
              </h2>
              <div className="flex flex-col gap-2">
                {dayReminders.map(r => {
                  const overdue = r.status === 'completed' && !r.taken
                  return (
                    <div
                      key={r.reminder_id}
                      className={`bg-white rounded-xl p-4 border shadow-sm flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 ${overdue ? 'border-amber-200' : 'border-blue-50'}`}
                    >
                      <div className="shrink-0 flex flex-col items-center min-w-[56px]">
                        {overdue
                          ? <AlertTriangle size={12} className="text-amber-400 mb-0.5" />
                          : <Clock size={12} className="text-gray-300 mb-0.5" />
                        }
                        <span className={`text-xs font-mono font-medium ${overdue ? 'text-amber-500' : 'text-gray-500'}`}>
                          {formatTime(r.scheduled_at)}
                        </span>
                        <span className="text-[10px] text-gray-400 mt-0.5 text-center leading-tight capitalize">
                          {formatShortDate(r.scheduled_at)}
                        </span>
                      </div>
                      <div className="w-px h-10 bg-gray-100 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Pill size={12} className={overdue ? 'text-amber-400 shrink-0' : 'text-blue-400 shrink-0'} />
                          <span className="text-sm font-semibold text-gray-800 truncate">{r.medication}</span>
                        </div>
                        <p className="text-xs text-gray-400 truncate mt-0.5">
                          {overdue ? 'Hora pasada, ¿ya lo tomaste?' : r.message}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_CLASSES[r.status]}`}>
                          {STATUS_LABELS[r.status]}
                        </span>
                        {r.taken ? (
                          <span className="flex items-center gap-1 text-xs text-green-600 font-medium">
                            <Check size={12} />
                            Tomado
                          </span>
                        ) : canMarkTaken(r.scheduled_at) ? (
                          <button
                            type="button"
                            onClick={() => handleTaken(r.reminder_id)}
                            className={`flex items-center gap-1 text-xs transition-colors ${overdue ? 'text-amber-400 hover:text-green-600' : 'text-gray-400 hover:text-green-600'}`}
                          >
                            <Check size={12} />
                            Marcar tomado
                          </button>
                        ) : (
                          <button
                            type="button"
                            disabled
                            title="No puedes marcar este medicamento como tomado hasta que falten menos de 2 horas para la toma."
                            className="flex items-center gap-1 text-xs text-gray-300 cursor-not-allowed"
                          >
                            <Check size={12} />
                            Marcar tomado
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
