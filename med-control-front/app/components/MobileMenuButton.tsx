'use client'
import { Menu } from 'lucide-react'

export default function MobileMenuButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="md:hidden fixed top-4 left-4 z-50 bg-white shadow-sm border border-blue-100 rounded-xl p-2.5 text-gray-600 hover:text-blue-500 transition-colors"
      aria-label="Abrir menú"
    >
      <Menu size={20} />
    </button>
  )
}
