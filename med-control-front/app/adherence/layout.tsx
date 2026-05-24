import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Adherencia',
}

export default function AdherenceLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
