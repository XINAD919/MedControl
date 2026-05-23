'use client'

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { fetchReminders, markReminderTaken } from './lib/api'
import type { Reminder, ReminderStatus } from './lib/types'
import { CalendarDays, Check, Clock, AlertTriangle } from 'lucide-react'

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

function toUtcDate(iso: string): Date {
  const hasOffset = /([+-]\d{2}:\d{2}|Z)$/.test(iso)
  return new Date(hasOffset ? iso : iso + 'Z')
}

function localDateKey(iso: string): string {
  const d = toUtcDate(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function localTodayKey(): string {
  return localDateKey(new Date().toISOString())
}

function formatTime(iso: string) {
  return toUtcDate(iso).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', hour12: true })
}

function isOverdue(r: Reminder): boolean {
  return r.status === 'completed' && !r.taken
}

function canMarkTaken(scheduledAt: string): boolean {
  return toUtcDate(scheduledAt).getTime() - Date.now() < 2 * 60 * 60 * 1000
}

function ReminderCard({ reminder, onTaken }: { reminder: Reminder; onTaken: (id: string) => void }) {
  const overdue = isOverdue(reminder)
  return (
    <div className={`bg-white rounded-2xl p-4 shadow-sm border flex flex-col gap-2 transition-colors ${
      reminder.taken ? 'border-green-100 opacity-75' : overdue ? 'border-amber-200' : 'border-blue-50'
    }`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          {overdue && <AlertTriangle size={13} className="text-amber-400 shrink-0" />}
          <span className={`font-semibold text-sm leading-tight ${reminder.taken ? 'line-through text-gray-400' : 'text-gray-800'}`}>
            {reminder.medication}
          </span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${STATUS_CLASSES[reminder.status]}`}>
          {STATUS_LABELS[reminder.status]}
        </span>
      </div>
      {overdue && (
        <p className="text-xs text-amber-500 font-medium">Hora pasada — ¿ya lo tomaste?</p>
      )}
      <p className="text-xs text-gray-400 line-clamp-2">{reminder.message}</p>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <Clock size={12} />
          <span>{formatTime(reminder.scheduled_at)}</span>
        </div>
        {reminder.taken ? (
          <span className="flex items-center gap-1 text-xs text-green-600 font-medium">
            <Check size={12} />
            Tomado
          </span>
        ) : canMarkTaken(reminder.scheduled_at) ? (
          <button
            onClick={() => onTaken(reminder.reminder_id)}
            className={`flex items-center gap-1 text-xs transition-colors ${overdue ? 'text-amber-400 hover:text-green-600' : 'text-gray-400 hover:text-green-600'}`}
          >
            <Check size={12} />
            Marcar tomado
          </button>
        ) : (
          <button
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
}

function Skeleton() {
  return (
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-blue-50 flex flex-col gap-3 animate-pulse">
      <div className="flex justify-between">
        <div className="h-3.5 bg-gray-100 rounded w-2/3" />
        <div className="h-3.5 bg-gray-100 rounded w-16" />
      </div>
      <div className="h-3 bg-gray-100 rounded w-full" />
      <div className="h-3 bg-gray-100 rounded w-1/3" />
    </div>
  )
}

export default function DashboardPage() {
  const { data: session, status } = useSession()
  const [todayReminders, setTodayReminders] = useState<Reminder[]>([])
  const [upcomingReminders, setUpcomingReminders] = useState<Reminder[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!session) return

    const load = () => {
      const today = localTodayKey()
      fetchReminders(session)
        .then((all) => {
          setTodayReminders(all.filter(r => localDateKey(r.scheduled_at) === today))
          const upcoming = all
            .filter(r => r.status === 'scheduled' && localDateKey(r.scheduled_at) !== today)
            .slice(0, 10)
          setUpcomingReminders(upcoming)
          setError(null)
        })
        .catch(err => setError(err.message))
        .finally(() => setLoading(false))
    }

    load()
    const interval = setInterval(load, 30_000)
    return () => clearInterval(interval)
  }, [session])

  function handleTaken(reminderId: string) {
    if (!session) return
    markReminderTaken(session, reminderId).then(() => {
      const patch = (r: Reminder) => r.reminder_id === reminderId ? { ...r, taken: true, taken_at: new Date().toISOString() } : r
      setTodayReminders(prev => prev.map(patch))
      setUpcomingReminders(prev => prev.map(patch))
    }).catch(() => {})
  }

  if (status === 'loading') return <div className="p-6 animate-pulse"><div className="h-6 bg-white rounded w-48" /></div>
  if (!session) return null

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Dashboard</h1>
        <p className="text-sm text-gray-400 mt-0.5">
          {new Date().toLocaleDateString('es-ES', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
        </p>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 text-red-600 text-sm rounded-xl border border-red-100">
          Error al cargar recordatorios: {error}
        </div>
      )}

      {/* Recordatorios de hoy */}
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-3">
          <CalendarDays size={16} className="text-blue-500" />
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wider">Hoy</h2>
          {!loading && (
            <span className="ml-auto text-xs text-gray-400">{todayReminders.length} recordatorio{todayReminders.length !== 1 ? 's' : ''}</span>
          )}
        </div>

        {loading ? (
          <div className="flex flex-col gap-3">
            <Skeleton />
            <Skeleton />
          </div>
        ) : todayReminders.length === 0 ? (
          <div className="bg-white rounded-2xl p-8 text-center border border-blue-50">
            <CalendarDays size={32} className="text-gray-200 mx-auto mb-2" />
            <p className="text-sm text-gray-400">No hay recordatorios para hoy</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {todayReminders.map(r => (
              <ReminderCard key={r.reminder_id} reminder={r} onTaken={handleTaken} />
            ))}
          </div>
        )}
      </section>

      {/* Próximos recordatorios */}
      {!loading && upcomingReminders.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Clock size={16} className="text-blue-500" />
            <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wider">Próximos</h2>
          </div>
          <div className="flex flex-col gap-3">
            {upcomingReminders.map(r => (
              <ReminderCard key={r.reminder_id} reminder={r} onTaken={handleTaken} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
