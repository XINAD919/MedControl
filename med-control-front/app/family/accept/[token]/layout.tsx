import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Aceptar invitación',
}

export default function AcceptLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
