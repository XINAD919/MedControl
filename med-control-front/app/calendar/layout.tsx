import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Calendario',
}

export default function CalendarLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
