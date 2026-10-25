'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { fetchChannels, createChannel, deleteChannel, toggleChannelReminders, sendVerification, verifyEmailCode } from '../lib/api'
import { canWrite } from '../lib/rbac'
import type { Channel, ChannelType } from '../lib/types'
import { Send, Mail, Hash, Bell, Phone, CheckCircle, AlertCircle, Trash2, ToggleLeft, ToggleRight, Plus, X, ChevronDown, ExternalLink, Loader2, ShieldCheck } from 'lucide-react'
import WhatsappIcon from '../components/icons/WhatsappIcon'

const toFlag = (cc: string) =>
  [...cc.toUpperCase()].map(c => String.fromCodePoint(c.charCodeAt(0) + 127397)).join('')

type Country = { name: string; iso: string; dial: string }

const COUNTRIES: Country[] = [
  { name: 'Colombia', iso: 'CO', dial: '+57' },
  { name: 'México', iso: 'MX', dial: '+52' },
  { name: 'Argentina', iso: 'AR', dial: '+54' },
  { name: 'Chile', iso: 'CL', dial: '+56' },
  { name: 'Perú', iso: 'PE', dial: '+51' },
  { name: 'Venezuela', iso: 'VE', dial: '+58' },
  { name: 'Ecuador', iso: 'EC', dial: '+593' },
  { name: 'Bolivia', iso: 'BO', dial: '+591' },
  { name: 'Paraguay', iso: 'PY', dial: '+595' },
  { name: 'Uruguay', iso: 'UY', dial: '+598' },
  { name: 'Brasil', iso: 'BR', dial: '+55' },
  { name: 'Costa Rica', iso: 'CR', dial: '+506' },
  { name: 'Panamá', iso: 'PA', dial: '+507' },
  { name: 'Guatemala', iso: 'GT', dial: '+502' },
  { name: 'Honduras', iso: 'HN', dial: '+504' },
  { name: 'El Salvador', iso: 'SV', dial: '+503' },
  { name: 'Nicaragua', iso: 'NI', dial: '+505' },
  { name: 'República Dominicana', iso: 'DO', dial: '+1809' },
  { name: 'Cuba', iso: 'CU', dial: '+53' },
  { name: 'Puerto Rico', iso: 'PR', dial: '+1787' },
  { name: 'España', iso: 'ES', dial: '+34' },
  { name: 'Estados Unidos', iso: 'US', dial: '+1' },
  { name: 'Canadá', iso: 'CA', dial: '+1' },
  { name: 'Reino Unido', iso: 'GB', dial: '+44' },
  { name: 'Francia', iso: 'FR', dial: '+33' },
  { name: 'Alemania', iso: 'DE', dial: '+49' },
  { name: 'Italia', iso: 'IT', dial: '+39' },
  { name: 'Portugal', iso: 'PT', dial: '+351' },
]

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

type VerifyState = 'idle' | 'sending' | 'entering_code' | 'waiting_whatsapp' | 'timed_out'

type VerifyFlow = {
  state: VerifyState
  emailCode: string
  error: string | null
  loading: boolean
  onEmailCodeChange: (v: string) => void
  onConfirmCode: () => void
  onResend: () => void
  onCancel: () => void
}

function ChannelRow({
  channel,
  onDelete,
  onToggle,
  onVerify,
  verifyFlow,
}: {
  channel: Channel
  onDelete: (c: ChannelType) => void
  onToggle: (c: ChannelType) => void
  onVerify: (c: ChannelType) => void
  verifyFlow?: VerifyFlow
}) {
  const isExpanded = verifyFlow &&
    (verifyFlow.state === 'entering_code' ||
     verifyFlow.state === 'waiting_whatsapp' ||
     verifyFlow.state === 'timed_out')

  return (
    <div className="bg-white rounded-2xl border border-blue-50 shadow-sm overflow-hidden">
      <div className="p-4 flex items-center gap-4">
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

        {/* Verification badge / actions */}
        <div className="shrink-0">
          {channel.verified ? (
            <CheckCircle size={16} className="text-green-400" />
          ) : verifyFlow?.state === 'sending' ? (
            <Loader2 size={16} className="text-blue-400 animate-spin" />
          ) : verifyFlow?.state === 'entering_code' ? (
            <ShieldCheck size={16} className="text-blue-400" />
          ) : verifyFlow?.state === 'waiting_whatsapp' ? (
            <div className="flex items-center gap-1 text-xs text-blue-500">
              <Loader2 size={13} className="animate-spin" />
              <span>Esperando...</span>
            </div>
          ) : verifyFlow?.state === 'timed_out' ? (
            <div className="flex items-center gap-1 text-xs text-amber-500">
              <AlertCircle size={14} />
              <span>Sin respuesta</span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-xs text-amber-500">
                <AlertCircle size={14} />
                <span>Pendiente</span>
              </div>
              <button
                type="button"
                onClick={() => onVerify(channel.channel)}
                className="text-xs text-blue-500 hover:text-blue-700 font-medium underline underline-offset-2 transition-colors"
              >
                Verificar
              </button>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={() => onToggle(channel.channel)}
          title={channel.receive_reminders ? 'Desactivar recordatorios' : 'Activar recordatorios'}
          className="shrink-0 text-gray-400 hover:text-blue-500 transition-colors"
        >
          {channel.receive_reminders
            ? <ToggleRight size={22} className="text-blue-500" />
            : <ToggleLeft size={22} />}
        </button>

        <button
          type="button"
          onClick={() => onDelete(channel.channel)}
          title="Eliminar canal"
          className="shrink-0 text-gray-300 hover:text-red-400 transition-colors"
        >
          <Trash2 size={16} />
        </button>
      </div>

      {/* Inline verification panel */}
      {isExpanded && verifyFlow && (
        <div className="px-4 pb-4 border-t border-blue-50">
          {verifyFlow.state === 'entering_code' && (
            <div className="pt-3">
              <p className="text-xs text-gray-500 mb-2">
                Ingresa el código de 6 dígitos que enviamos a tu correo:
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={verifyFlow.emailCode}
                  onChange={e => verifyFlow.onEmailCodeChange(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="000000"
                  className="w-28 border border-gray-200 rounded-xl px-3 py-2 text-sm text-center font-mono tracking-widest focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
                <button
                  type="button"
                  onClick={verifyFlow.onConfirmCode}
                  disabled={verifyFlow.loading || verifyFlow.emailCode.length < 6}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm bg-blue-500 text-white rounded-xl font-medium hover:bg-blue-600 disabled:opacity-50 transition-colors"
                >
                  {verifyFlow.loading
                    ? <Loader2 size={13} className="animate-spin" />
                    : 'Confirmar'}
                </button>
                <button
                  type="button"
                  onClick={verifyFlow.onResend}
                  className="px-3 py-2 text-sm text-gray-400 hover:text-gray-600 font-medium transition-colors"
                >
                  Reenviar
                </button>
                <button
                  type="button"
                  onClick={verifyFlow.onCancel}
                  className="ml-auto text-gray-300 hover:text-gray-400 transition-colors"
                >
                  <X size={14} />
                </button>
              </div>
              {verifyFlow.error && (
                <p className="text-xs text-red-500 mt-2">{verifyFlow.error}</p>
              )}
            </div>
          )}

          {verifyFlow.state === 'waiting_whatsapp' && (
            <div className="pt-3 flex items-start gap-3">
              <p className="text-xs text-gray-600 flex-1">
                Te enviamos una encuesta por WhatsApp. Selecciona{' '}
                <strong className="font-semibold">"Sí, soy yo"</strong>{' '}
                para verificar tu número.
              </p>
              <button
                type="button"
                onClick={verifyFlow.onCancel}
                className="shrink-0 text-gray-300 hover:text-gray-400 transition-colors pt-0.5"
              >
                <X size={14} />
              </button>
            </div>
          )}

          {verifyFlow.state === 'timed_out' && (
            <div className="pt-3 flex items-center gap-3">
              <p className="text-xs text-amber-600 flex-1">
                No se recibió respuesta. ¿Intentar de nuevo?
              </p>
              <button
                type="button"
                onClick={() => onVerify(channel.channel)}
                className="text-xs text-blue-500 hover:text-blue-700 font-medium transition-colors"
              >
                Reintentar
              </button>
              <button
                type="button"
                onClick={verifyFlow.onCancel}
                className="text-gray-300 hover:text-gray-400 transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          )}
        </div>
      )}
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
  const [formChannel, setFormChannel] = useState<AddableChannel>('whatsapp')
  const [formNotifyId, setFormNotifyId] = useState('')
  const [formWebhookUrl, setFormWebhookUrl] = useState('')
  const [formIsPrimary, setFormIsPrimary] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formCountryIso, setFormCountryIso] = useState('CO')
  const [formCountryOpen, setFormCountryOpen] = useState(false)
  const [formLocalNumber, setFormLocalNumber] = useState('')
  const countryDropdownRef = useRef<HTMLDivElement>(null)

  // Verification flow
  const [verifyingChannel, setVerifyingChannel] = useState<ChannelType | null>(null)
  const [verifyState, setVerifyState] = useState<VerifyState>('idle')
  const [emailCode, setEmailCode] = useState('')
  const [verifyError, setVerifyError] = useState<string | null>(null)
  const [verifyLoading, setVerifyLoading] = useState(false)
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollCountRef = useRef(0)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (countryDropdownRef.current && !countryDropdownRef.current.contains(e.target as Node)) {
        setFormCountryOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
    }
  }, [])

  const fetchAndSetChannels = useCallback(() => {
    if (!session) return
    fetchChannels(session, false)
      .then(setChannels)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [session])

  const load = () => {
    setLoading(true)
    fetchAndSetChannels()
  }

  useEffect(() => {
    fetchAndSetChannels()
  }, [fetchAndSetChannels])

  const stopPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }

  const startWhatsAppPolling = (activeSession: NonNullable<typeof session>) => {
    pollCountRef.current = 0
    pollIntervalRef.current = setInterval(async () => {
      pollCountRef.current++
      if (pollCountRef.current >= 60) {
        stopPolling()
        setVerifyState('timed_out')
        return
      }
      try {
        const updated = await fetchChannels(activeSession, false)
        const wa = updated.find(c => c.channel === 'whatsapp')
        if (wa?.verified) {
          stopPolling()
          setChannels(updated)
          setVerifyingChannel(null)
          setVerifyState('idle')
        }
      } catch {
        // ignore transient errors during polling
      }
    }, 5000)
  }

  const handleVerify = async (channel: ChannelType) => {
    if (!session) return
    stopPolling()
    setVerifyingChannel(channel)
    setVerifyState('sending')
    setVerifyError(null)
    setEmailCode('')
    try {
      await sendVerification(session, channel)
      if (channel === 'email') {
        setVerifyState('entering_code')
      } else {
        setVerifyState('waiting_whatsapp')
        startWhatsAppPolling(session)
      }
    } catch (err) {
      setVerifyError((err as Error).message)
      setVerifyState('idle')
      setVerifyingChannel(null)
    }
  }

  const handleConfirmEmailCode = async () => {
    if (!session || emailCode.length < 6) return
    setVerifyLoading(true)
    setVerifyError(null)
    try {
      await verifyEmailCode(session, emailCode)
      setVerifyingChannel(null)
      setVerifyState('idle')
      load()
    } catch (err) {
      setVerifyError((err as Error).message)
    } finally {
      setVerifyLoading(false)
    }
  }

  const handleResendCode = async () => {
    if (!session || verifyingChannel !== 'email') return
    setVerifyError(null)
    setEmailCode('')
    try {
      await sendVerification(session, 'email')
    } catch (err) {
      setVerifyError((err as Error).message)
    }
  }

  const handleCancelVerification = () => {
    stopPolling()
    setVerifyingChannel(null)
    setVerifyState('idle')
    setVerifyError(null)
    setEmailCode('')
  }

  const handleDelete = async (channel: ChannelType) => {
    if (!session) return
    if (verifyingChannel === channel) handleCancelVerification()
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
      const isPhone = formChannel === 'whatsapp'
      const selectedCountry = COUNTRIES.find(c => c.iso === formCountryIso) ?? COUNTRIES[0]
      const notifyId = isPhone ? `${selectedCountry.dial}${formLocalNumber}` : formNotifyId
      await createChannel(session, {
        channel: formChannel,
        notify_id: notifyId,
        is_primary: formIsPrimary,
        receive_reminders: true,
        metadata,
      })
      setShowForm(false)
      setFormNotifyId('')
      setFormWebhookUrl('')
      setFormLocalNumber('')
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
    <div className="p-4 sm:p-6 pt-16 sm:pt-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-800">Configuración</h1>
        <p className="text-sm text-gray-400 mt-0.5">Gestiona tus canales de notificación</p>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 text-red-600 text-sm rounded-xl border border-red-100 flex justify-between items-start">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} className="ml-2 shrink-0"><X size={14} /></button>
        </div>
      )}

      {verifyError && !verifyingChannel && (
        <div className="mb-4 px-4 py-3 bg-amber-50 text-amber-700 text-sm rounded-xl border border-amber-100 flex justify-between items-start">
          <span>{verifyError}</span>
          <button type="button" onClick={() => setVerifyError(null)} className="ml-2 shrink-0"><X size={14} /></button>
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
            {channels.map(ch => {
              const isActive = verifyingChannel === ch.channel
              const verifyFlow: VerifyFlow | undefined = isActive ? {
                state: verifyState,
                emailCode,
                error: verifyError,
                loading: verifyLoading,
                onEmailCodeChange: setEmailCode,
                onConfirmCode: handleConfirmEmailCode,
                onResend: handleResendCode,
                onCancel: handleCancelVerification,
              } : undefined

              return (
                <ChannelRow
                  key={ch.channel}
                  channel={ch}
                  onDelete={handleDelete}
                  onToggle={handleToggle}
                  onVerify={handleVerify}
                  verifyFlow={verifyFlow}
                />
              )
            })}
          </div>
        )}
      </section>

      {/* Add channel */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wider">Agregar canal</h2>
          {writeAllowed && !showForm && (
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="flex items-center gap-1.5 text-sm text-blue-500 hover:text-blue-700 font-medium"
            >
              <Plus size={16} />
              Agregar
            </button>
          )}
        </div>
        {!writeAllowed && (
          <p className="text-xs text-amber-500 mb-3">Solo lectura: no puedes agregar ni eliminar canales.</p>
        )}

        {showForm && (
          <form
            onSubmit={handleAddChannel}
            className="bg-white rounded-2xl p-5 border border-blue-100 shadow-sm flex flex-col gap-4"
          >
            {/* Channel type */}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1.5">Canal</p>
              <div className="flex gap-2 flex-wrap">
                {ADDABLE_CHANNELS.map(ch => (
                  <button
                    key={ch}
                    type="button"
                    onClick={() => { setFormChannel(ch); setFormNotifyId(''); setFormWebhookUrl(''); setFormLocalNumber('') }}
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
              {formChannel === 'telegram' && (
                <p className="text-xs text-gray-400 mb-1.5">
                  Para obtener tu Chat ID: abre{' '}
                  <a
                    href="https://t.me/userinfobot"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-500 hover:text-blue-700 inline-flex items-center gap-0.5 font-medium"
                  >
                    @userinfobot
                    <ExternalLink size={11} />
                  </a>
                  {' '}en Telegram, presiona <strong>Start</strong> y copia el número que te envía.
                </p>
              )}
              {formChannel === 'whatsapp' ? (
                <div className="flex gap-2">
                  <div ref={countryDropdownRef} className="relative">
                    <button
                      type="button"
                      onClick={() => setFormCountryOpen(o => !o)}
                      className="flex items-center gap-1.5 border border-gray-200 rounded-xl px-3 py-2.5 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-200 whitespace-nowrap"
                    >
                      <span className="text-base leading-none">{toFlag(formCountryIso)}</span>
                      <span>{COUNTRIES.find(c => c.iso === formCountryIso)?.dial ?? '+57'}</span>
                      <ChevronDown size={14} className="text-gray-400" />
                    </button>
                    {formCountryOpen && (
                      <div className="absolute top-full left-0 mt-1 z-50 bg-white border border-gray-200 rounded-xl shadow-lg max-h-60 overflow-y-auto min-w-[220px]">
                        {COUNTRIES.map(c => (
                          <button
                            key={c.iso}
                            type="button"
                            onClick={() => { setFormCountryIso(c.iso); setFormCountryOpen(false) }}
                            className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-blue-50 transition-colors ${formCountryIso === c.iso ? 'bg-blue-50 text-blue-600' : 'text-gray-700'}`}
                          >
                            <span className="text-base leading-none">{toFlag(c.iso)}</span>
                            <span className="flex-1">{c.name}</span>
                            <span className="text-gray-400">{c.dial}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <input
                    type="tel"
                    aria-label="Número de teléfono local"
                    value={formLocalNumber}
                    onChange={e => setFormLocalNumber(e.target.value.replace(/\D/g, '').slice(0, 10))}
                    required
                    maxLength={10}
                    placeholder="3001234567"
                    className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
                  />
                </div>
              ) : (
                <input
                  type={formChannel === 'email' ? 'email' : 'text'}
                  aria-label={NOTIFY_ID_LABELS[formChannel]}
                  value={formNotifyId}
                  onChange={e => setFormNotifyId(e.target.value)}
                  required
                  placeholder={formChannel === 'telegram' ? '123456789' : formChannel === 'email' ? 'correo@ejemplo.com' : 'ID de usuario'}
                  className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
              )}
            </div>

            {/* Discord webhook URL */}
            {formChannel === 'discord' && (
              <div>
                <label htmlFor="discord-webhook" className="text-xs font-medium text-gray-500 mb-1.5 block">Webhook URL</label>
                <input
                  id="discord-webhook"
                  aria-label="Webhook URL de Discord"
                  type="url"
                  value={formWebhookUrl}
                  onChange={e => setFormWebhookUrl(e.target.value)}
                  required
                  placeholder="https://discord.com/api/webhooks/..."
                  className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
                />
              </div>
            )}

            {!hasPrimaryChannel && (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  aria-label="Canal principal"
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
