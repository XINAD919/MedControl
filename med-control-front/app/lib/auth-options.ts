import { SignJWT } from 'jose'
import type { DefaultSession, NextAuthOptions } from 'next-auth'
import AzureADProvider from 'next-auth/providers/azure-ad'
import Credentials from 'next-auth/providers/credentials'
import Google from 'next-auth/providers/google'

declare module 'next-auth' {
  interface Session {
    accessToken: string
    idToken?: string
    user: {
      id: string
      role: string
      linkedPatientIds: string[]
    } & DefaultSession['user']
  }
  interface User {
    role?: string
    linkedPatientIds?: string[]
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    provider?: string
    accessToken?: string
    idToken?: string
  }
}

const API_INTERNAL = process.env.API_INTERNAL_URL ?? 'http://localhost:8000'
const AUTH_SECRET_INTERNAL = process.env.AUTH_SECRET_INTERNAL ?? ''

async function resolveBackendUser(
  email: string,
  provider: string,
  name?: string | null,
): Promise<{ id: string; role: string; linked_patient_ids: string[] }> {
  const res = await fetch(`${API_INTERNAL}/api/auth/oauth-user`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Auth-Secret': AUTH_SECRET_INTERNAL,
    },
    body: JSON.stringify({ email, provider, name }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`Backend user resolution failed (${res.status}): ${text}`)
  }
  return res.json() as Promise<{ id: string; role: string; linked_patient_ids: string[] }>
}

async function fetchLinkedPatientIds(userId: string): Promise<string[]> {
  const res = await fetch(
    `${API_INTERNAL}/api/family/linked-patient-ids?user_id=${userId}`,
    { headers: { 'X-Auth-Secret': AUTH_SECRET_INTERNAL } },
  )
  if (!res.ok) return []
  return res.json() as Promise<string[]>
}

const providers: NextAuthOptions['providers'] = []

if (process.env.AUTH_AZURE_AD_CLIENT_ID && process.env.AUTH_AZURE_AD_CLIENT_SECRET) {
  providers.push(AzureADProvider({
    clientId: process.env.AUTH_AZURE_AD_CLIENT_ID,
    clientSecret: process.env.AUTH_AZURE_AD_CLIENT_SECRET,
    tenantId: process.env.AUTH_AZURE_AD_TENANT_ID as string,
    checks: ['pkce', 'state'],
  }))
}

if (process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET) {
  providers.push(Google({
    clientId: process.env.AUTH_GOOGLE_ID,
    clientSecret: process.env.AUTH_GOOGLE_SECRET,
  }))
}

export const authOptions: NextAuthOptions = {
  providers: [
    ...providers,
    Credentials({
      name: 'Credenciales',
      credentials: {
        email: { label: 'Correo electrónico', type: 'email' },
        password: { label: 'Contraseña', type: 'password' },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null

        const res = await fetch(`${API_INTERNAL}/api/auth/login`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Auth-Secret': AUTH_SECRET_INTERNAL,
          },
          body: JSON.stringify({
            email: credentials.email,
            password: credentials.password,
          }),
        })

        if (!res.ok) return null

        const backendUser: { id: string; role: string; linked_patient_ids: string[] } = await res.json()
        return {
          id: backendUser.id,
          email: credentials.email as string,
          name: (credentials.email as string).split('@')[0],
          role: backendUser.role,
          linkedPatientIds: backendUser.linked_patient_ids ?? [],
        }
      },
    }),
  ],
  secret: process.env.NEXTAUTH_SECRET as string,
  callbacks: {
    async jwt({ token, user, account, trigger }: any) {
      if (trigger === 'signIn' && user) {
        if (account?.provider === 'credentials') {
          token.userId = user.id ?? ''
          token.role = user.role ?? 'USER'
          token.linkedPatientIds = user.linkedPatientIds ?? []
        } else {
          const backendUser = await resolveBackendUser(
            user.email,
            account.provider,
            user.name,
          )
          token.userId = backendUser.id
          token.role = backendUser.role
          token.linkedPatientIds = backendUser.linked_patient_ids ?? []
        }
      }
      // Refrescar linkedPatientIds al hacer session.update() (p.ej. tras aceptar invitación)
      if (trigger === 'update' && token.userId) {
        token.linkedPatientIds = await fetchLinkedPatientIds(token.userId as string)
        token.backendToken = undefined // forzar regeneración
      }
      if (token.userId && (!token.backendToken || trigger === 'signIn' || trigger === 'update')) {
        token.backendToken = await new SignJWT({ userId: token.userId, role: token.role })
          .setProtectedHeader({ alg: 'HS256' })
          .setIssuedAt()
          .setExpirationTime('24h')
          .sign(new TextEncoder().encode(AUTH_SECRET_INTERNAL))
      }
      return token
    },

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    session({ session, token }: any) {
      session.user.id = (token.userId as string) ?? ''
      session.user.role = (token.role as string) ?? 'USER'
      session.user.linkedPatientIds = (token.linkedPatientIds as string[]) ?? []
      session.accessToken = (token.backendToken as string) ?? ''
      return session
    },
  },
}
