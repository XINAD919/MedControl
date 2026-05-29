'use client'

import { signIn } from 'next-auth/react'
import Link from 'next/link'
import { Suspense, useState } from 'react'
import { useSearchParams } from 'next/navigation'

function RegisterForm() {
  const searchParams = useSearchParams()
  const caregiverToken = searchParams.get('caregiver_token')

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleOAuth = (provider: 'google' | 'azure-ad') => {
    setLoading(provider)
    signIn(provider, { callbackUrl: '/' })
  }

  const handleRegister = async (e: React.SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    setLoading('credentials')
    setError(null)

    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, username, password, caregiver_token: caregiverToken }),
    })

    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      setError(data.detail ?? 'Error al crear la cuenta. Intenta de nuevo.')
      setLoading(null)
      return
    }

    await signIn('credentials', { email, password, callbackUrl: caregiverToken ? '/family' : '/' })
  }

  return (
    <div className="min-h-screen bg-blue-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-3xl shadow-sm border border-blue-100 p-8 w-full max-w-sm">

        {/* Header */}
        <div className="flex flex-col items-center mb-8 gap-2">
          <div className="bg-blue-500 rounded-2xl p-3.5 flex items-center justify-center mb-1">
            <svg viewBox="0 0 24 24" className="size-7 text-white" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-gray-900">MedControl</h1>
          <p className="text-sm text-gray-400">Crea tu cuenta</p>
        </div>

        {/* Banner de cuidador */}
        {caregiverToken && (
          <div className="mb-5 px-4 py-3 bg-blue-50 text-blue-600 text-sm rounded-xl border border-blue-100">
            Estás registrándote como cuidador/a. Al completar el registro quedarás vinculado automáticamente al paciente que te invitó.
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div className="mb-5 px-4 py-3 bg-red-50 text-red-600 text-sm rounded-xl border border-red-100">
            {error}
          </div>
        )}

        {/* OAuth buttons */}
        <div className="flex flex-col gap-3 mb-6">
          <button
            type="button"
            onClick={() => handleOAuth('google')}
            disabled={loading !== null}
            className="flex items-center justify-center gap-3 w-full border border-gray-200 rounded-xl px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            <svg viewBox="0 0 24 24" className="size-5 shrink-0" aria-hidden>
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            {loading === 'google' ? 'Redirigiendo...' : 'Continuar con Google'}
          </button>

          <button
            type="button"
            onClick={() => handleOAuth('azure-ad')}
            disabled={loading !== null}
            className="flex items-center justify-center gap-3 w-full border border-gray-200 rounded-xl px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            <svg viewBox="0 0 23 23" className="size-5 shrink-0" aria-hidden>
              <path fill="#f25022" d="M1 1h10v10H1z" />
              <path fill="#00a4ef" d="M12 1h10v10H12z" />
              <path fill="#7fba00" d="M1 12h10v10H1z" />
              <path fill="#ffb900" d="M12 12h10v10H12z" />
            </svg>
            {loading === 'azure-ad' ? 'Redirigiendo...' : 'Continuar con Microsoft'}
          </button>
        </div>

        {/* Divider */}
        <div className="flex items-center gap-3 mb-5">
          <div className="flex-1 h-px bg-gray-100" />
          <span className="text-xs text-gray-400">o con credenciales</span>
          <div className="flex-1 h-px bg-gray-100" />
        </div>

        {/* Credentials form */}
        <form onSubmit={handleRegister} className="flex flex-col gap-3">
          <div>
            <label htmlFor="reg-name" className="text-xs font-medium text-gray-500 mb-1 block">
              Nombre completo
            </label>
            <input
              id="reg-name"
              aria-label="Nombre completo"
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              required
              autoComplete="name"
              placeholder="Juan Pérez"
              className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200 transition"
            />
          </div>
          <div>
            <label htmlFor="reg-email" className="text-xs font-medium text-gray-500 mb-1 block">
              Correo electrónico
            </label>
            <input
              id="reg-email"
              aria-label="Correo electrónico"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoComplete="email"
              placeholder="tu@correo.com"
              className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200 transition"
            />
          </div>
          <div>
            <label htmlFor="reg-username" className="text-xs font-medium text-gray-500 mb-1 block">
              Nombre de usuario
            </label>
            <input
              id="reg-username"
              aria-label="Nombre de usuario"
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoComplete="username"
              placeholder="juanperez"
              className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200 transition"
            />
          </div>
          <div>
            <label htmlFor="reg-password" className="text-xs font-medium text-gray-500 mb-1 block">
              Contraseña
            </label>
            <input
              id="reg-password"
              aria-label="Contraseña"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete="new-password"
              placeholder="••••••••"
              className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200 transition"
            />
          </div>
          <button
            type="submit"
            disabled={loading !== null}
            className="w-full bg-blue-500 text-white rounded-xl py-2.5 text-sm font-medium hover:bg-blue-600 disabled:opacity-50 transition-colors mt-1"
          >
            {loading === 'credentials' ? 'Creando cuenta...' : 'Crear cuenta'}
          </button>
        </form>

        <p className="text-center text-xs text-gray-400 mt-5">
          ¿Ya tienes una cuenta?{' '}
          <Link href="/login" className="text-blue-500 font-medium hover:underline">
            Inicia sesión
          </Link>
        </p>

      </div>
    </div>
  )
}

export default function RegisterPage() {
  return (
    <Suspense fallback={<div className="min-h-screen animate-pulse bg-blue-50" />}>
      <RegisterForm />
    </Suspense>
  )
}
