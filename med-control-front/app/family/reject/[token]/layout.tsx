import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Rechazar invitación',
}

export default function RejectLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
