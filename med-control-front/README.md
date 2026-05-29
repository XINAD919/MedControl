# MedControl Frontend

Frontend web de MedControl, un asistente de adherencia médica que ayuda a los pacientes a gestionar sus recordatorios de medicación. Toda la UI está en español.

## Funcionalidades

- **Dashboard** — recordatorios del día + próximos, con opción de marcar como tomado
- **Chat con IA** — conversación por WebSocket con el agente médico; subida de recetas (PDF/imagen) con análisis por OCR
- **Calendario** — agenda cronológica de recordatorios filtrable por estado/fecha/medicamento
- **Canales de notificación** — configuración de WhatsApp, Telegram, Email, Discord, SMS y Web Push
- **Adherencia** — métricas de cumplimiento (score 1-5, tasa de adherencia, puntualidad) generadas por LLM en ventana de 30 días
- **Familia** — gestión de cuidadores: invitaciones por email, aceptación/rechazo por token, vista de paciente vinculado para caregivers

## Tech Stack

- **Next.js 16.2.4** — App Router
- **React 19.2.4** — TypeScript strict
- **Tailwind CSS v4** — `@import "tailwindcss"`, sin tailwind.config.js
- **NextAuth.js v4** — Credentials + Google OAuth + Azure AD
- **lucide-react** — iconos
- **react-markdown v10** — renderizado Markdown en el chat

## Requisitos previos

- Node.js 18+
- Backend FastAPI corriendo (por defecto en `http://localhost:8000`)

## Quick start

```bash
npm install
cp .env.local.example .env.local   # editar variables
npm run dev                         # http://localhost:3000
```

## Variables de entorno

| Variable | Requerida | Descripción |
|---|---|---|
| `NEXTAUTH_SECRET` | Sí | Secreto de sesión de NextAuth |
| `AUTH_SECRET_INTERNAL` | Sí | Clave para firmar el JWT enviado al backend (HS256) |
| `API_INTERNAL_URL` | No | URL del backend desde el servidor (default: `http://localhost:8000`) |
| `NEXT_PUBLIC_WS_URL` | No | URL WebSocket del backend (default: `ws://localhost:8000`) |
| `AUTH_GOOGLE_ID` | No | Client ID de Google OAuth |
| `AUTH_GOOGLE_SECRET` | No | Client Secret de Google OAuth |
| `AUTH_AZURE_AD_CLIENT_ID` | No | Client ID de Azure AD |
| `AUTH_AZURE_AD_CLIENT_SECRET` | No | Client Secret de Azure AD |
| `AUTH_AZURE_AD_TENANT_ID` | No | Tenant ID de Azure AD |

## Scripts

```bash
npm run dev      # servidor de desarrollo en http://localhost:3000
npm run build    # build de producción
npm run start    # servidor de producción
npm run lint     # ESLint
```

## Estructura del proyecto

```
app/
├── lib/
│   ├── types.ts          # Interfaces TypeScript (Reminder, Channel, AdherenceAnalysis, …)
│   ├── api.ts            # Todas las llamadas a la API + helper WebSocket
│   ├── auth-options.ts   # Configuración NextAuth (providers, callbacks JWT/session)
│   └── rbac.ts           # Control de acceso por rol (canWrite / assertCanWrite)
├── components/
│   ├── SideBar.tsx        # Barra de navegación lateral
│   ├── NavItem.tsx        # Enlace de nav con detección de ruta activa
│   ├── ClientLayout.tsx   # Layout cliente: sidebar + toggle móvil
│   └── MobileMenuButton.tsx
├── api/auth/[...nextauth]/ # Route handler de NextAuth
├── page.tsx               # Dashboard
├── chat/                  # Chat IA + subida de recetas
├── calendar/              # Agenda cronológica
├── settings/              # Canales de notificación
├── adherence/             # Métricas de adherencia
├── notifications/         # Historial de notificaciones
├── family/                # Gestión de familia/cuidadores
│   ├── accept/[token]/    # Aceptar invitación
│   └── reject/[token]/    # Rechazar invitación
├── login/                 # Login
└── register/              # Registro de usuario
```

## Despliegue

Railway con Nixpacks. Configurado en `railway.json`: healthcheck en `/`, comando de inicio `npm run start`.

La reescritura de API está en `next.config.ts`: `/api/backend/*` → `API_INTERNAL_URL/*`.
