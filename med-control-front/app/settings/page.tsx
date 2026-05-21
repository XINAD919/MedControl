'use client'

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { fetchChannels, createChannel, deleteChannel, toggleChannelReminders } from '../lib/api'
import { canWrite } from '../lib/rbac'
import type { Channel, ChannelType } from '../lib/types'
import { Send, Mail, Hash, Bell, Phone, CheckCircle, AlertCircle, Trash2, ToggleLeft, ToggleRight, Plus, X } from 'lucide-react'
import WhatsappIcon from '../components/icons/WhatsappIcon'

const CHANNEL_ICONS: Record<ChannelType, React.ReactNode> = {
  whatsapp: <WhatsappIcon size={16} />,
  telegram: <Send size={16} />,
  email: <Mail size={16} />,
  discord: <Hash size={16} />,
  webpush: <Bell size={16} />,
  sms: <Phone size={16} />,
}

const CHANNEL_LABELS: Record<ChannelType, string> = {
  whatsapp: 'WhatsApp',
  telegram: 'Telegram',
  email: 'Correo electrónico',
  discord: 'Discord',
  webpush: 'Web Push',
  sms: 'SMS',
}

const NOTIFY_ID_LABELS: Record<ChannelType, string> = {
  whatsapp: 'Numero de telefono',
  telegram: 'Chat ID (número)',
  email: 'Dirección de correo',
  discord: 'User ID',
  webpush: '',
  sms: 'Número de teléfono',
}

type AddableChannel = 'whatsapp' | 'telegram' | 'email' | 'discord'

const ADDABLE_CHANNELS: AddableChannel[] = ['whatsapp', 'telegram', 'email', 'discord']

function ChannelRow({
  channel,
  onDelete,
  onToggle,
}: {
  channel: Channel
  onDelete: (c: ChannelType) => void
  onToggle: (c: ChannelType) => void
}) {
  return (
    <div className="bg-white rounded-2xl p-4 border border-blue-50 shadow-sm flex items-center gap-4">
      <div className={`p-2 rounded-xl ${channel.verified ? 'bg-blue-50 text-blue-500' : 'bg-gray-50 text-gray-400'}`}>
        {CHANNEL_ICONS[channel.channel]}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-800">{CHANNEL_LABELS[channel.channel]}</span>
          {channel.is_primary && (
            <span className="text-xs bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded-full font-medium">Principal</span>
          )}
        </div>
        <span className="text-xs text-gray-400 truncate block">{channel.notify_id}</span>
      </div>

      {/* Verified badge */}
      <div className="shrink-0">
        {channel.verified ? (
          <CheckCircle size={16} className="text-green-400" />
        ) : (
          <div className="flex items-center gap-1 text-xs text-amber-500">
            <AlertCircle size={14} />
            <span>Pendiente</span>
          </div>
        )}
      </div>

      {/* Recordatorios toggle */}
      <button
        onClick={() => onToggle(channel.channel)}
        title={channel.receive_reminders ? 'Desactivar recordatorios' : 'Activar recordatorios'}
        className="shrink-0 text-gray-400 hover:text-blue-500 transition-colors"
      >
        {channel.receive_reminders
          ? <ToggleRight size={22} className="text-blue-500" />
          : <ToggleLeft size={22} />}
      </button>

      {/* Delete */}
      <button
        onClick={() => onDelete(channel.channel)}
        title="Eliminar canal"
        className="shrink-0 text-gray-300 hover:text-red-400 transition-colors"
      >
        <Trash2 size={16} />
      </button>
    </div>
  )
}

export default function SettingsPage() {
  const { data: session, status } = useSession()
  const [channels, setChannels] = useState<Channel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Add channel form
  const [showForm, setShowForm] = useState(false)
  const [formChannel, setFormChannel] = useState<AddableChannel>('telegram')
  const [formNotifyId, setFormNotifyId] = useState('')
  const [formWebhookUrl, setFormWebhookUrl] = useState('')
  const [formIsPrimary, setFormIsPrimary] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [formLoading, setFormLoading] = useState(false)

  const load = () => {
    if (!session) return
    setLoading(true)
    fetchChannels(session, false)
      .then(setChannels)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [session]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelete = async (channel: ChannelType) => {
    if (!session) return
    try {
      await deleteChannel(session, channel)
      setChannels(prev => prev.filter(c => c.channel !== channel))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const handleToggle = async (channel: ChannelType) => {
    if (!session) return
    try {
      const result = await toggleChannelReminders(session, channel)
      setChannels(prev =>
        prev.map(c => c.channel === channel ? { ...c, receive_reminders: result.receive_reminders } : c)
      )
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const handleAddChannel = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!session) return
    setFormError(null)
    setFormLoading(true)
    try {
      const metadata: Record<string, unknown> = {}
      if (formChannel === 'discord' && formWebhookUrl) {
        metadata.webhook_url = formWebhookUrl
      }
      await createChannel(session, {
        channel: formChannel,
        notify_id: formNotifyId,
        is_primary: formIsPrimary,
        receive_reminders: true,
        metadata,
      })
      setShowForm(false)
      setFormNotifyId('')
      setFormWebhookUrl('')
      setFormIsPrimary(false)
      load()
    } catch (err) {
      setFormError((err as Error).message)
    } finally {
      setFormLoading(false)
    }
  }

  if (status === 'loading') return <div className="p-6 animate-pulse"><div className="h-6 bg-white rounded w-48" /></div>
  if (!session) return null

  const writeAllowed = canWrite(session)

  const hasPrimaryChannel = channels.some(c => c.is_primary)

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Configuración</h1>
        <p className="text-sm text-gray-400 mt-0.5">Gestiona tus canales de notificación</p>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 text-red-600 text-sm rounded-xl border border-red-100 flex justify-between items-start">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-2 shrink-0"><X size={14} /></button>
        </div>
      )}

      {/* Channel list */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wider mb-3">Canales configurados</h2>

        {loading ? (
          <div className="flex flex-col gap-3 animate-pulse">
            <div className="h-16 bg-white rounded-2xl border border-blue-50" />
            <div className="h-16 bg-white rounded-2xl border border-blue-50" />
          </div>
        ) : channels.length === 0 ? (
          <div className="bg-white rounded-2xl p-8 text-center border border-blue-50">
            <Bell size={32} className="text-gray-200 mx-auto mb-2" />
            <p className="text-sm text-gray-400">No hay canales configurados</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {channels.map(ch => (
              <ChannelRow
                key={ch.channel}
                channel={ch}
                onDelete={handleDelete}
                onToggle={handleToggle}
              />
            ))}
          </div>
        )}
      </section>

      {/* Add channel */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wider">Agregar canal</h2>
          {writeAllowed && !showForm && (
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-1.5 text-sm text-blue-500 hover:text-blue-700 font-medium"
            >
              <Plus size={16} />
              Agregar
            </button>
          )}
        </div>
        {!writeAllowed && (
          <p className="text-xs text-amber-500 mb-3">Solo lectura — no puedes agregar ni eliminar canales.</p>
        )}

        {showForm && (
          <form
            onSubmit={handleAddChannel}
            className="bg-white rounded-2xl p-5 border border-blue-100 shadow-sm flex flex-col gap-4"
          >
            {/* Channel type */}
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1.5 block">Canal</label>
              <div className="flex gap-2">
                {ADDABLE_CHANNELS.map(ch => (
                  <button
                    key={ch}
                    type="button"
                    onClick={() => { setFormChannel(ch); setFormNotifyId(''); setFormWebhookUrl('') }}
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium border transition-colors ${formChannel === ch
                      ? 'bg-blue-50 border-blue-200 text-blue-600'
                      : 'bg-gray-50 border-gray-100 text-gray-500 hover:border-blue-100'
                      }`}
                  >
                    {CHANNEL_ICONS[ch]}
                    {CHANNEL_LABELS[ch]}
                  </button>
                ))}
              </div>
            </div>

            {/* Notify ID */}
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1.5 block">
                {NOTIFY_ID_LABELS[formChannel]}
              </label>
              <input
                type={formChannel === 'email' ? 'email' : 'text'}
                value={formNotifyId}
                onChange={e => setFormNotifyId(e.target.value)}
                required
                placeholder={formChannel === 'whatsapp' ? '+521234567890' : formChannel === 'telegram' ? '123456789' : formChannel === 'email' ? 'correo@ejemplo.com' : 'ID de usuario'}
                className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
            </div>

            {/* Discord webhook URL */}
            {formChannel === 'discord' && (
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1.5 block">Webhook URL</label>
                <input
                  type="url"
                  value={formWebhookUrl}
                  onChange={e => setFormWebhookUrl(e.target.value)}
                  required
                  placeholder="https://discord.com/api/webhooks/..."
                  className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
              </div>
            )}
            {/* Primary checkbox */}
            {!hasPrimaryChannel && (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formIsPrimary}
                  onChange={e => setFormIsPrimary(e.target.checked)}
                  className="rounded"
                />
                <span className="text-sm text-gray-600">Canal principal</span>
              </label>
            )}


            {formError && (
              <p className="text-xs text-red-500">{formError}</p>
            )}

            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => { setShowForm(false); setFormError(null) }}
                className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 font-medium"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={formLoading}
                className="px-4 py-2 text-sm bg-blue-500 text-white rounded-xl font-medium hover:bg-blue-600 disabled:opacity-50 transition-colors"
              >
                {formLoading ? 'Guardando...' : 'Guardar canal'}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  )
}
