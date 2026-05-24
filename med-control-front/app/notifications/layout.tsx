import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Notificaciones',
}

export default function NotificationsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
