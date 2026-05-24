'use client'

import { use, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import { CheckCircle, XCircle } from 'lucide-react'
import { acceptInvitation } from '../../../lib/api'

export default function AcceptInvitationPage({
  params,
}: {
  params: Promise<{ token: string }>
}) {
  const { token } = use(params)
  const { data: session, status, update } = useSession()
  const { push } = useRouter()

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  if (status === 'loading') return <div className="min-h-screen animate-pulse bg-blue-50" />

  if (!session) {
    push(`/login?callbackUrl=/family/accept/${token}`)
    return null
  }

  if (done) {
    return (
      <div className="min-h-screen bg-blue-50 flex items-center justify-center">
        <div className="bg-white rounded-3xl shadow-sm border border-blue-100 p-8 w-full max-w-sm text-center">
          <CheckCircle size={40} className="text-green-500 mx-auto mb-4" />
          <h1 className="text-xl font-semibold text-gray-900 mb-2">¡Invitación aceptada!</h1>
          <p className="text-sm text-gray-400">Redirigiendo al panel…</p>
        </div>
      </div>
    )
  }

  async function handleAccept() {
    if (!session) return
    setLoading(true)
    setError(null)
    try {
      await acceptInvitation(session, token)
      setDone(true)
      // Refrescar sesión para que el rol CAREGIVER se refleje en el JWT
      await update()
      setTimeout(() => push('/family'), 1800)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error al aceptar la invitación')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-blue-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-3xl shadow-sm border border-blue-100 p-8 w-full max-w-sm text-center">
        <CheckCircle size={36} className="text-blue-400 mx-auto mb-4" />
        <h1 className="text-xl font-semibold text-gray-900 mb-2">Invitación de cuidador/a</h1>
        <p className="text-sm text-gray-500 mb-6">
          ¿Deseas aceptar esta invitación y convertirte en cuidador/a de este paciente?
        </p>
        {error && (
          <div className="flex items-center justify-center gap-2 text-sm text-red-500 mb-4">
            <XCircle size={14} />
            {error}
          </div>
        )}
        <button
          type="button"
          onClick={handleAccept}
          disabled={loading}
          className="w-full bg-blue-500 text-white rounded-xl py-2.5 text-sm font-medium hover:bg-blue-600 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Procesando…' : 'Aceptar invitación'}
        </button>
        <button
          type="button"
          onClick={() => push('/')}
          className="mt-3 w-full text-sm text-gray-400 hover:text-gray-600 transition-colors"
        >
          Cancelar
        </button>
      </div>
    </div>
  )
}
