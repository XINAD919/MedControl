import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Registro',
}

export default function RegisterLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
