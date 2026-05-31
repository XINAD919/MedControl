'use client'

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { UserPlus, Trash2, Mail, Users, Clock, CheckCircle, XCircle, RefreshCw, Ban, TrendingUp, TrendingDown, Minus, Flame, BarChart2, Loader2, AlertTriangle, Pill } from 'lucide-react'
import {
  fetchFamilyMembers,
  fetchLinkedPatients,
  fetchFamilyInvitations,
  inviteFamilyMember,
  removeFamilyMember,
  resendInvitation,
  revokeInvitation,
  fetchPatientAdherenceAnalysis,
  generatePatientAdherenceAnalysis,
  fetchPatientDelayedReminders,
  fetchPatientMedicationsSummary,
  sendManualReminder,
  type DelayedReminder,
} from '../lib/api'
import type { AdherenceAnalysis, FamilyMember, FamilyInvitation, InvitationStatus, LinkedPatient, MedicationSummary } from '../lib/types'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type TabId = 'dashboard' | 'familiares'

const INVITATION_STATUS_CLASSES: Record<InvitationStatus, string> = {
  pending:  'bg-yellow-100 text-yellow-700',
  accepted: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-600',
  expired:  'bg-gray-100 text-gray-500',
  revoked:  'bg-gray-100 text-gray-400',
}

const INVITATION_STATUS_LABELS: Record<InvitationStatus, string> = {
  pending:  'Pendiente',
  accepted: 'Aceptada',
  rejected: 'Rechazada',
  expired:  'Expirada',
  revoked:  'Revocada',
}

function SkeletonList() {
  return (
    <div className="flex flex-col gap-2 animate-pulse">
      {[1, 2, 3].map(i => (
        <div key={i} className="bg-white rounded-2xl p-4 h-16 border border-blue-50" />
      ))}
    </div>
  )
}


function MemberRow({ member, onRemove }: { member: FamilyMember; onRemove: (id: string) => void }) {
  const displayName = member.name || member.email || member.caregiver_id
  const initial = displayName.charAt(0).toUpperCase()
  return (
    <div className="bg-white rounded-2xl px-4 py-3 border border-blue-50 flex items-center gap-3">
      <div className="size-9 rounded-full bg-green-100 text-green-700 flex items-center justify-center font-bold text-sm shrink-0">
        {initial}
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-medium text-gray-800 text-sm truncate">{displayName}</p>
        {member.name && member.email && (
          <p className="text-xs text-gray-400 truncate">{member.email}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onRemove(member.caregiver_id)}
        className="text-gray-300 hover:text-red-400 transition-colors p-1 rounded-lg"
        title="Eliminar cuidador"
      >
        <Trash2 size={15} />
      </button>
    </div>
  )
}

function InvitationRow({
  invitation,
  onResend,
  onRevoke,
}: {
  invitation: FamilyInvitation
  onResend: (id: string) => Promise<void>
  onRevoke: (id: string) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)

  async function handle(action: (id: string) => Promise<void>) {
    setBusy(true)
    try { await action(invitation.id) } finally { setBusy(false) }
  }

  const canResend = invitation.status === 'pending' || invitation.status === 'expired'
  const canRevoke = invitation.status === 'pending'

  return (
    <div className="bg-white rounded-2xl px-4 py-3 border border-blue-50 flex items-center gap-3">
      <Mail size={15} className="text-gray-300 shrink-0" />
      <p className="flex-1 text-sm text-gray-700 truncate">{invitation.invited_email}</p>
      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${INVITATION_STATUS_CLASSES[invitation.status]}`}>
        {INVITATION_STATUS_LABELS[invitation.status]}
      </span>
      {canResend && (
        <button
          type="button"
          disabled={busy}
          onClick={() => handle(onResend)}
          title="Reenviar invitación"
          className="text-gray-300 hover:text-blue-400 transition-colors p-1 rounded-lg disabled:opacity-40"
        >
          <RefreshCw size={14} />
        </button>
      )}
      {canRevoke && (
        <button
          type="button"
          disabled={busy}
          onClick={() => handle(onRevoke)}
          title="Revocar invitación"
          className="text-gray-300 hover:text-red-400 transition-colors p-1 rounded-lg disabled:opacity-40"
        >
          <Ban size={14} />
        </button>
      )}
    </div>
  )
}

export default function FamilyPage() {
  const { data: session, status } = useSession()
  const [activeTab, setActiveTab] = useState<TabId>('familiares')

  const isCaregiver = (session?.user?.linkedPatientIds?.length ?? 0) > 0

  // Tab 1 (dashboard) state
  const [patients, setPatients] = useState<LinkedPatient[]>([])
  const [patientsLoading, setPatientsLoading] = useState(false)
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(null)
  const [adherence, setAdherence] = useState<AdherenceAnalysis | null>(null)
  const [adherenceLoading, setAdherenceLoading] = useState(false)
  const [generatingAnalysis, setGeneratingAnalysis] = useState(false)
  const [delayedReminders, setDelayedReminders] = useState<DelayedReminder[]>([])
  const [medicationSummary, setMedicationSummary] = useState<MedicationSummary[]>([])

  // Tab 2 state
  const [members, setMembers] = useState<FamilyMember[]>([])
  const [invitations, setInvitations] = useState<FamilyInvitation[]>([])
  const [tab2Loading, setTab2Loading] = useState(true)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviting, setInviting] = useState(false)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [inviteSuccess, setInviteSuccess] = useState(false)

  useEffect(() => {
    if (!session) return
    if (activeTab === 'dashboard') {
      fetchLinkedPatients(session)
        .then(setPatients)
        .catch(() => {})
        .finally(() => setPatientsLoading(false))
    }
    if (activeTab === 'familiares') {
      Promise.all([fetchFamilyMembers(session), fetchFamilyInvitations(session)])
        .then(([m, i]) => { setMembers(m); setInvitations(i) })
        .catch(() => {})
        .finally(() => setTab2Loading(false))
    }
  }, [session, activeTab])

  async function handleInvite(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!session) return
    setInviting(true)
    setInviteError(null)
    setInviteSuccess(false)
    try {
      await inviteFamilyMember(session, inviteEmail)
      setInviteSuccess(true)
      setInviteEmail('')
      fetchFamilyInvitations(session).then(setInvitations).catch(() => {})
    } catch (err: unknown) {
      setInviteError(err instanceof Error ? err.message : 'Error al enviar la invitación')
    } finally {
      setInviting(false)
    }
  }

  async function handleSelectPatient(patientId: string) {
    if (!session) return
    setSelectedPatientId(patientId)
    setAdherence(null)
    setDelayedReminders([])
    setMedicationSummary([])
    setAdherenceLoading(true)
    Promise.all([
      fetchPatientAdherenceAnalysis(session, patientId).catch(() => null),
      fetchPatientDelayedReminders(session, patientId).catch(() => []),
      fetchPatientMedicationsSummary(session, patientId).catch(() => []),
    ]).then(([a, d, m]) => {
      setAdherence(a)
      setDelayedReminders(d)
      setMedicationSummary(m)
    }).finally(() => setAdherenceLoading(false))
  }

  async function handleSendManualReminder(reminderId: string) {
    if (!session || !selectedPatientId) return
    await sendManualReminder(session, selectedPatientId, reminderId).catch(() => {})
    setDelayedReminders(prev => prev.map(r =>
      r.reminder_id === reminderId ? { ...r, manual_reminder_sent: true } : r,
    ))
  }

  async function handleGenerateAnalysis() {
    if (!session || !selectedPatientId) return
    setGeneratingAnalysis(true)
    generatePatientAdherenceAnalysis(session, selectedPatientId, 30)
      .then(setAdherence)
      .catch(() => {})
      .finally(() => setGeneratingAnalysis(false))
  }

  async function handleRemove(caregiverId: string) {
    if (!session) return
    await removeFamilyMember(session, caregiverId).catch(() => {})
    setMembers(prev => prev.filter(m => m.caregiver_id !== caregiverId))
  }

  async function handleResend(invitationId: string) {
    if (!session) return
    await resendInvitation(session, invitationId).catch(() => {})
  }

  async function handleRevoke(invitationId: string) {
    if (!session) return
    await revokeInvitation(session, invitationId).catch(() => {})
    setInvitations(prev => prev.map(i => i.id === invitationId ? { ...i, status: 'revoked' as const } : i))
  }

  if (status === 'loading') return <div className="p-6 animate-pulse" />
  if (!session) return null

  return (
    <div className="p-4 sm:p-6 pt-16 sm:pt-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-800">Familia</h1>
        <p className="text-sm text-gray-400 mt-0.5">Gestiona tus cuidadores y acceso compartido</p>
      </div>

      {/* Tab bar — Dashboard solo visible para cuidadores */}
      <div className="flex gap-1 mb-6 bg-gray-100 p-1 rounded-xl">
        {(isCaregiver
          ? [['dashboard', 'Dashboard'], ['familiares', 'Familiares']] as [TabId, string][]
          : [['familiares', 'Familiares']] as [TabId, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => {
              setActiveTab(id)
              if (id === 'dashboard') {
                setPatientsLoading(true)
              } else if (id === 'familiares') {
                setTab2Loading(true)
              }
            }}
            className={`flex-1 py-2 px-4 rounded-lg text-sm font-medium transition-colors ${
              activeTab === id
                ? 'bg-white text-blue-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Tab 1: Dashboard ───────────────────────────────────────────────── */}
      {activeTab === 'dashboard' && (
        <section className="flex flex-col gap-4">
          {patientsLoading ? (
            <SkeletonList />
          ) : patients.length === 0 ? (
            <div className="bg-white rounded-2xl p-8 text-center border border-blue-50">
              <Users size={32} className="text-gray-200 mx-auto mb-3" />
              <p className="text-sm text-gray-400">Aún no tienes pacientes vinculados.</p>
            </div>
          ) : (
            <>
              {/* Selector de paciente */}
              <div className="flex flex-wrap gap-2">
                {patients.map(p => {
                  const label = p.name || p.email || p.patient_id
                  const active = selectedPatientId === p.patient_id
                  return (
                    <button
                      key={p.patient_id}
                      type="button"
                      onClick={() => handleSelectPatient(p.patient_id)}
                      className={`px-3 py-1.5 rounded-xl text-sm font-medium transition-colors border ${
                        active
                          ? 'bg-blue-500 text-white border-blue-500'
                          : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
                      }`}
                    >
                      {label}
                    </button>
                  )
                })}
              </div>

              {/* Dosis retrasadas */}
              {selectedPatientId && (
                <div className="bg-white rounded-2xl border border-amber-100 shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-amber-50 flex items-center gap-2">
                    <AlertTriangle size={14} className="text-amber-400" />
                    <p className="text-sm font-semibold text-gray-700">Dosis retrasadas</p>
                    {delayedReminders.length > 0 && (
                      <span className="ml-auto text-xs text-amber-500 font-medium">{delayedReminders.length}</span>
                    )}
                  </div>
                  {adherenceLoading ? (
                    <div className="px-4 py-4 flex items-center gap-2 text-gray-400 text-sm">
                      <Loader2 size={14} className="animate-spin" />
                      Cargando…
                    </div>
                  ) : delayedReminders.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-gray-400">No hay dosis retrasadas en este momento.</p>
                  ) : (
                    <div className="flex flex-col divide-y divide-gray-50">
                      {delayedReminders.map(r => (
                        <div key={r.reminder_id} className="px-4 py-3 flex items-center gap-3">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-800 truncate">{r.medication}</p>
                            <p className="text-xs text-gray-400">{new Date(r.scheduled_at).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}</p>
                          </div>
                          <button
                            type="button"
                            disabled={r.manual_reminder_sent}
                            onClick={() => handleSendManualReminder(r.reminder_id)}
                            className={`shrink-0 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
                              r.manual_reminder_sent
                                ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                                : 'bg-amber-50 text-amber-600 hover:bg-amber-100'
                            }`}
                          >
                            {r.manual_reminder_sent ? 'Enviado' : 'Recordar'}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Panel de medicamentos */}
              {selectedPatientId && (
                <div className="bg-white rounded-2xl border border-blue-50 shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-blue-50 flex items-center gap-2">
                    <Pill size={14} className="text-blue-400" />
                    <p className="text-sm font-semibold text-gray-700">Medicamentos</p>
                    {medicationSummary.length > 0 && (
                      <span className="ml-auto text-xs text-blue-400 font-medium">{medicationSummary.length}</span>
                    )}
                  </div>
                  {adherenceLoading ? (
                    <div className="px-4 py-4 flex items-center gap-2 text-gray-400 text-sm">
                      <Loader2 size={14} className="animate-spin" />
                      Cargando…
                    </div>
                  ) : medicationSummary.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-gray-400">No hay medicamentos registrados en los últimos 30 días.</p>
                  ) : (
                    <div className="flex flex-col divide-y divide-gray-50">
                      {medicationSummary.map(med => (
                        <div key={med.medication} className="px-4 py-3 flex items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-800 truncate">{med.medication}</p>
                            <p className="text-xs text-gray-400 mt-0.5">{med.taken}/{med.total_due} dosis tomadas</p>
                            {med.is_recurring && (
                              <p className="text-xs text-blue-400 mt-0.5">
                                {med.remaining_doses === null
                                  ? 'Tratamiento continuo'
                                  : `${med.remaining_doses} dosis restantes`}
                              </p>
                            )}
                          </div>
                          <div className="shrink-0 flex items-center gap-1 mt-0.5">
                            {med.has_missed ? (
                              <>
                                <AlertTriangle size={13} className="text-amber-400" />
                                <span className="text-xs text-amber-500 font-medium">{med.missed} omitida{med.missed !== 1 ? 's' : ''}</span>
                              </>
                            ) : (
                              <CheckCircle size={14} className="text-green-400" />
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Panel de adherencia */}
              {selectedPatientId && (
                <div className="bg-white rounded-2xl border border-blue-50 shadow-sm overflow-hidden">
                  {adherenceLoading ? (
                    <div className="p-8 flex items-center justify-center gap-2 text-gray-400 text-sm">
                      <Loader2 size={16} className="animate-spin" />
                      Cargando métricas…
                    </div>
                  ) : adherence ? (
                    <div className="p-5 flex flex-col gap-4">
                      {/* Score + trend */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={`text-3xl font-bold ${
                            adherence.score >= 4 ? 'text-green-500' :
                            adherence.score >= 2.5 ? 'text-yellow-500' : 'text-red-500'
                          }`}>{adherence.score.toFixed(1)}</span>
                          <span className="text-sm text-gray-400">/5</span>
                        </div>
                        <div className="flex items-center gap-1.5 text-sm">
                          {adherence.metrics.trend === 'mejorando' && <TrendingUp size={15} className="text-green-500" />}
                          {adherence.metrics.trend === 'empeorando' && <TrendingDown size={15} className="text-red-400" />}
                          {adherence.metrics.trend === 'estable' && <Minus size={15} className="text-gray-400" />}
                          <span className={
                            adherence.metrics.trend === 'mejorando' ? 'text-green-600' :
                            adherence.metrics.trend === 'empeorando' ? 'text-red-500' : 'text-gray-500'
                          }>{adherence.metrics.trend}</span>
                        </div>
                      </div>

                      {/* Métricas clave */}
                      <div className="grid grid-cols-3 gap-3">
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-xs text-gray-400 mb-1">Adherencia</p>
                          <p className="text-lg font-semibold text-gray-800">{Math.round(adherence.metrics.adherence_rate * 100)}%</p>
                        </div>
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-xs text-gray-400 mb-1">Tomadas</p>
                          <p className="text-lg font-semibold text-gray-800">{adherence.metrics.total_taken}/{adherence.metrics.total_due}</p>
                        </div>
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-xs text-gray-400 mb-1 flex items-center justify-center gap-0.5">
                            <Flame size={11} className="text-orange-400" /> Racha
                          </p>
                          <p className="text-lg font-semibold text-gray-800">{adherence.metrics.streak_days}d</p>
                        </div>
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-xs text-gray-400 mb-1">Puntualidad</p>
                          <p className="text-lg font-semibold text-gray-800">{Math.round(adherence.metrics.punctuality_rate * 100)}%</p>
                        </div>
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-xs text-gray-400 mb-1">Retraso medio</p>
                          <p className="text-lg font-semibold text-gray-800">{Math.round(adherence.metrics.avg_delay_minutes)}<span className="text-sm font-normal text-gray-500"> min</span></p>
                        </div>
                        <div className="bg-gray-50 rounded-xl p-3 text-center">
                          <p className="text-xs text-gray-400 mb-1">Últimos 7d</p>
                          <p className="text-lg font-semibold text-gray-800">{Math.round(adherence.metrics.recent_adherence_rate * 100)}%</p>
                        </div>
                      </div>

                      {/* Comentario LLM */}
                      <div className="md-prose text-sm text-gray-600 leading-relaxed">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{adherence.llm_comment}</ReactMarkdown>
                      </div>

                      <p className="text-xs text-gray-300">
                        Análisis de {adherence.period_days} días · {new Date(adherence.created_at).toLocaleDateString('es-ES')}
                      </p>
                    </div>
                  ) : (
                    <div className="p-8 text-center">
                      <BarChart2 size={28} className="text-gray-200 mx-auto mb-3" />
                      <p className="text-sm text-gray-400 mb-4">No hay análisis disponible para este paciente.</p>
                    </div>
                  )}

                  <div className="border-t border-gray-50 px-5 py-3">
                    <button
                      type="button"
                      disabled={generatingAnalysis}
                      onClick={handleGenerateAnalysis}
                      className="flex items-center gap-1.5 text-sm text-blue-500 hover:text-blue-600 disabled:opacity-50 transition-colors"
                    >
                      {generatingAnalysis
                        ? <><Loader2 size={13} className="animate-spin" /> Generando…</>
                        : <><RefreshCw size={13} /> {adherence ? 'Regenerar análisis' : 'Generar análisis'}</>
                      }
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {/* ── Tab 2: Familiares ──────────────────────────────────────────────── */}
      {activeTab === 'familiares' && (
        <section className="flex flex-col gap-6">

          {/* Formulario de invitación */}
          <div className="bg-white rounded-2xl p-5 border border-blue-50 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
              <UserPlus size={15} className="text-blue-500" />
              Invitar cuidador/a
            </h2>
            {inviteSuccess && (
              <div className="flex items-center gap-2 text-sm text-green-600 mb-3">
                <CheckCircle size={14} />
                Invitación enviada correctamente.
              </div>
            )}
            {inviteError && (
              <div className="flex items-center gap-2 text-sm text-red-500 mb-3">
                <XCircle size={14} />
                {inviteError}
              </div>
            )}
            <form onSubmit={handleInvite} className="flex gap-2">
              <input
                type="email"
                aria-label="Correo del cuidador"
                value={inviteEmail}
                onChange={e => setInviteEmail(e.target.value)}
                required
                placeholder="correo@ejemplo.com"
                className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
              <button
                type="submit"
                disabled={inviting}
                className="bg-blue-500 text-white rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-blue-600 disabled:opacity-50 transition-colors shrink-0"
              >
                {inviting ? 'Enviando…' : 'Invitar'}
              </button>
            </form>
          </div>

          {/* Cuidadores activos */}
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
              Cuidadores activos
            </h2>
            {tab2Loading ? (
              <SkeletonList />
            ) : members.length === 0 ? (
              <div className="bg-white rounded-2xl p-6 text-center border border-blue-50">
                <p className="text-sm text-gray-400">No hay cuidadores vinculados aún.</p>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {members.map(m => (
                  <MemberRow key={m.caregiver_id} member={m} onRemove={handleRemove} />
                ))}
              </div>
            )}
          </div>

          {/* Invitaciones enviadas */}
          {invitations.length > 0 && (
            <div>
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                <Clock size={12} />
                Invitaciones enviadas
              </h2>
              <div className="flex flex-col gap-2">
                {invitations.map(inv => (
                  <InvitationRow key={inv.id} invitation={inv} onResend={handleResend} onRevoke={handleRevoke} />
                ))}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
