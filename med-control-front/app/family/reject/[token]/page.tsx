'use client'

import { use, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import { XCircle } from 'lucide-react'
import { rejectInvitation } from '../../../lib/api'

export default function RejectInvitationPage({
  params,
}: {
  params: Promise<{ token: string }>
}) {
  const { token } = use(params)
  const { data: session, status } = useSession()
  const { push } = useRouter()

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  if (status === 'loading') return <div className="min-h-screen animate-pulse bg-blue-50" />

  if (!session) {
    push(`/login?callbackUrl=/family/reject/${token}`)
    return null
  }

  if (done) {
    return (
      <div className="min-h-screen bg-blue-50 flex items-center justify-center">
        <div className="bg-white rounded-3xl shadow-sm border border-blue-100 p-8 w-full max-w-sm text-center">
          <XCircle size={40} className="text-gray-400 mx-auto mb-4" />
          <h1 className="text-xl font-semibold text-gray-900 mb-2">Invitación rechazada</h1>
          <p className="text-sm text-gray-400">Redirigiendo al inicio…</p>
        </div>
      </div>
    )
  }

  async function handleReject() {
    if (!session) return
    setLoading(true)
    setError(null)
    try {
      await rejectInvitation(session, token)
      setDone(true)
      setTimeout(() => push('/'), 1800)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error al rechazar la invitación')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-blue-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-3xl shadow-sm border border-blue-100 p-8 w-full max-w-sm text-center">
        <XCircle size={36} className="text-gray-400 mx-auto mb-4" />
        <h1 className="text-xl font-semibold text-gray-900 mb-2">Rechazar invitación</h1>
        <p className="text-sm text-gray-500 mb-6">
          ¿Confirmas que deseas rechazar esta invitación de cuidador/a?
        </p>
        {error && (
          <p className="text-sm text-red-500 mb-4">{error}</p>
        )}
        <button
          type="button"
          onClick={handleReject}
          disabled={loading}
          className="w-full bg-gray-100 text-gray-700 rounded-xl py-2.5 text-sm font-medium hover:bg-gray-200 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Procesando…' : 'Rechazar invitación'}
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
