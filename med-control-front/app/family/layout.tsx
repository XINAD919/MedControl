import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Familia',
}

export default function FamilyLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
