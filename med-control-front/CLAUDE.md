# MedControl Frontend

Next.js 16.2.4 frontend para el asistente médico MedAI. Toda la UI está en español.

## Dev commands

```bash
npm run dev      # servidor de desarrollo en http://localhost:3000
npm run build    # build de producción
npm run lint     # ESLint
```

Requiere el backend FastAPI corriendo en `http://localhost:8000`.

## Stack

- **Next.js 16.2.4** — App Router, sin Pages Router
- **React 19.2.4** — usar `'use client'` para cualquier componente que necesite hooks o APIs del navegador
- **Tailwind CSS v4** — `@import "tailwindcss"` en globals.css; sin tailwind.config.js
- **TypeScript** — modo estricto
- **NextAuth.js v4** — autenticación (Credentials, Google, Azure AD)
- **lucide-react** — iconos
- **react-markdown v10** — renderizado Markdown en el chat

## Next.js 16: cambios que afectan el código

- `params` y `searchParams` en page/layout son async — deben awaitearse
- ESM-only packages (react-markdown v10) funcionan nativamente; no hace falta `transpilePackages`

## Estructura del proyecto

```
app/
├── lib/
│   ├── types.ts          # Interfaces TypeScript (Reminder, Channel, AdherenceAnalysis, …)
│   ├── api.ts            # Todas las llamadas a la API + helper WebSocket
│   ├── auth-options.ts   # Configuración NextAuth
│   └── rbac.ts           # canWrite / assertCanWrite
├── components/
│   ├── SideBar.tsx        # Barra de navegación lateral
│   ├── NavItem.tsx        # Nav link con detección de ruta activa
│   ├── ClientLayout.tsx   # Layout cliente: sidebar + toggle móvil
│   └── MobileMenuButton.tsx
├── api/auth/[...nextauth]/ # Route handler de NextAuth
├── page.tsx               # Dashboard
├── chat/                  # Chat IA + subida de recetas OCR
├── calendar/              # Agenda cronológica
├── settings/              # Canales de notificación
├── adherence/             # Métricas de adherencia
├── notifications/         # Historial de notificaciones
├── family/                # Gestión de familia/cuidadores
│   ├── accept/[token]/
│   └── reject/[token]/
├── login/
└── register/
```

## Autenticación

NextAuth v4 configurado en `app/lib/auth-options.ts`.

**Proveedores activos según env vars:**

- Credentials (email/password) — siempre activo, llama a `/api/auth/login` en el backend
- Google OAuth — si `AUTH_GOOGLE_ID` + `AUTH_GOOGLE_SECRET` están definidos
- Azure AD — si `AUTH_AZURE_AD_CLIENT_ID` + `AUTH_AZURE_AD_CLIENT_SECRET` están definidos

**JWT interno:** tras el login, NextAuth genera un JWT HS256 firmado con `AUTH_SECRET_INTERNAL` que incluye `{ userId, role }`. Este token se guarda como `session.accessToken` y se envía al backend como `Authorization: Bearer <token>`.

**Shape de la sesión:**

```typescript
session.user.id; // UUID del usuario en el backend
session.user.role; // 'USER' | 'CAREGIVER'
session.accessToken; // JWT firmado para el backend
```

**Middleware de protección de rutas:** `proxy.ts` (NextAuth middleware) protege todas las rutas excepto `/login`, `/register` y `/api/auth`.

## RBAC

`app/lib/rbac.ts` define dos roles:

- **USER** — acceso completo de lectura/escritura
- **CAREGIVER** — solo lectura; las mutaciones lanzan error

Antes de cualquier llamada que modifique datos, `api.ts` llama a `assertCanWrite(session)`. Los componentes pueden usar `canWrite(session)` para condicionar la UI.

## API proxy

`next.config.ts` reescribe `/api/backend/*` → `API_INTERNAL_URL/*` (default `http://localhost:8000`).

Todos los fetch en `api.ts` usan `BASE_URL = '/api/backend'`, por lo que el backend nunca se llama directamente desde el cliente.

## Integración con el backend

Todas las funciones de API están en `app/lib/api.ts`. Usan `session.user.id` como identificador de usuario y `session.accessToken` como Bearer token.

Endpoints principales:

| Función                        | Método | Ruta                                                  |
| ------------------------------ | ------ | ----------------------------------------------------- |
| `fetchReminders`               | GET    | `/api/users/{id}/reminders`                           |
| `markReminderTaken`            | PATCH  | `/api/users/{id}/reminders/{rid}/taken`               |
| `fetchChannels`                | GET    | `/api/users/{id}/channels`                            |
| `createChannel`                | POST   | `/api/users/{id}/channels`                            |
| `deleteChannel`                | DELETE | `/api/users/{id}/channels/{channel}`                  |
| `toggleChannelReminders`       | PATCH  | `/api/users/{id}/channels/{channel}/toggle-reminders` |
| `fetchNotifications`           | GET    | `/api/users/{id}/notifications`                       |
| `uploadDocument`               | POST   | `/api/users/{id}/documents` (multipart)               |
| `fetchLatestAdherenceAnalysis` | GET    | `/api/users/{id}/adherence-analysis/latest`           |
| `generateAdherenceAnalysis`    | POST   | `/api/users/{id}/adherence-analysis?period_days=30`   |
| `fetchFamilyMembers`           | GET    | `/api/family/members`                                 |
| `fetchLinkedPatients`          | GET    | `/api/family/linked-patients`                         |
| `inviteFamilyMember`           | POST   | `/api/family/invite`                                  |
| `removeFamilyMember`           | DELETE | `/api/family/members/{id}`                            |
| `acceptInvitation`             | POST   | `/api/family/accept/{token}`                          |
| `rejectInvitation`             | POST   | `/api/family/reject/{token}`                          |

## WebSocket (chat)

Una conexión por mensaje — el backend cierra la conexión al terminar la respuesta. Sin sentinel `[DONE]`; `ws.onclose` dispara `onDone`.

```typescript
connectChatSocket(session, message, onToken, onDone, onError);
// onToken: acumula tokens de texto
// onDone: se llama cuando la conexión cierra (respuesta completa)
```

URL: `NEXT_PUBLIC_WS_URL/ws/chat?session_id={userId}&token={accessToken}`

## Tailwind v4: clases dinámicas

Nunca construir clases por interpolación — Tailwind v4 no las detecta:

```typescript
// MAL
className={`bg-${color}-100`}

// BIEN — usar objeto de lookup con clases completas
const STATUS_CLASSES = {
  scheduled: 'bg-blue-100 text-blue-600',
  completed: 'bg-green-100 text-green-700',
}
```

## Markdown en el chat

Los mensajes del chat usan la clase CSS `.md-prose` (definida en `globals.css`) para estilo prose sin `@tailwindcss/typography`.

## Validacion de Codigo

Se corre el comando `npx tsc --noEmit` para validar que el codigo este bien escrito y sea tipado correctamente.
Se corre despues el comando `npx react-doctor@latest` para validar que el codigo este bien escrito y sea compatible con react y next.js.
Por ultimo se corre el comando `npm run lint` para validar que el codigo este bien escrito y sea compatible con el linter.
