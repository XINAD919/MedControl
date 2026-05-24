'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

type Props = {
  icon: React.ReactElement
  path: string
  title: string
  onClose?: () => void
}

function NavItem({ icon, path, title, onClose }: Props) {

  const pathname = usePathname()

  const isActivePath = pathname === path

  return (
    <Link
      href={path}
      onClick={onClose}
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 w-full transition-colors ${
        isActivePath
          ? 'bg-blue-50 text-blue-600'
          : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
      }`}
    >
      {icon}
      <span className={`text-sm font-semibold ${isActivePath ? 'text-blue-600' : 'text-gray-700'}`}>
        {title}
      </span>
      {isActivePath && <span className="ml-auto size-1.5 rounded-full bg-blue-500" />}
    </Link>
  )
}

export default NavItem