'use client'
import Image from 'next/image'
import NavItem from './NavItem'
import { LayoutDashboard, CalendarDays, MessageSquare, Users, Settings, LogOut, Bell, BarChart2 } from 'lucide-react'
import { useSession, signOut } from 'next-auth/react'

function SideBar() {
  const { data: session } = useSession()

  const displayName = session?.user?.name ?? 'Usuario'
  const displayEmail = session?.user?.email ?? ''
  const avatarSrc = session?.user?.image ?? '/assets/user-profile.png'
  const isCaregiver = session?.user?.role === 'CAREGIVER'

  return (
    <aside className='bg-white w-72 h-dvh flex flex-col rounded-r-2xl shadow-sm border-r border-blue-100'>
      {/* Logo / App header */}
      <div className="flex flex-row gap-3 items-center px-5 py-6">
        <div className="bg-blue-500 rounded-xl p-2 flex items-center justify-center">
          <Image src="/assets/user-profile.png" alt="app-logo" width={32} height={32} className='rounded-full' />
        </div>
        <div className="flex flex-col">
          <h1 className='font-bold text-base text-gray-900'>MedControl</h1>
          <span className='text-xs text-gray-400'>Tu compañero de tratamiento</span>
        </div>
      </div>

      <div className="mx-5 border-t border-gray-100" />

      {/* Badge de solo lectura para cuidadores */}
      {isCaregiver && (
        <div className="mx-3 mt-3 px-3 py-1.5 bg-amber-50 border border-amber-100 rounded-xl text-xs text-amber-600 font-medium text-center">
          Modo cuidador — solo lectura
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 flex flex-col gap-1">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-3 mb-2">Menú</p>
        <NavItem path='/' title='Dashboard' icon={<LayoutDashboard size={18} />} />
        <NavItem path='/calendar' title='Calendario' icon={<CalendarDays size={18} />} />
        <NavItem path='/chat' title='Chat' icon={<MessageSquare size={18} />} />
        <NavItem path='/family' title='Familia' icon={<Users size={18} />} />
        <NavItem path='/notifications' title='Notificaciones' icon={<Bell size={18} />} />
        <NavItem path='/adherence' title='Adherencia' icon={<BarChart2 size={18} />} />
        <NavItem path='/settings' title='Configuración' icon={<Settings size={18} />} />
      </nav>

      {/* User profile footer */}
      <div className="mx-5 border-t border-gray-100" />
      <div className="flex flex-row gap-3 items-center px-5 py-5">
        <div className="relative shrink-0">
          <Image
            src={avatarSrc}
            alt="user-profile"
            width={40}
            height={40}
            className='rounded-full ring-2 ring-blue-100'
          />
          <span className="absolute bottom-0 right-0 w-2.5 h-2.5 bg-green-400 rounded-full ring-2 ring-white" />
        </div>
        <div className="flex flex-col min-w-0 flex-1">
          <span className='font-semibold text-sm text-gray-900 truncate'>{displayName}</span>
          <span className='text-xs text-gray-400 truncate'>{displayEmail}</span>
        </div>
        <button
          onClick={() => signOut({ callbackUrl: '/login' })}
          title="Cerrar sesión"
          className="shrink-0 text-gray-300 hover:text-red-400 transition-colors p-1.5 rounded-lg hover:bg-red-50"
        >
          <LogOut size={16} />
        </button>
      </div>
    </aside>
  )
}

export default SideBar
