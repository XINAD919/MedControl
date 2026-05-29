'use client';

import SideBar from "./SideBar";
import MobileMenuButton from "./MobileMenuButton";
import OneSignal from 'react-onesignal';
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

const PUBLIC_ROUTES = ['/login', '/register'];

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();
  const { push } = useRouter();
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (status === 'unauthenticated' && !PUBLIC_ROUTES.includes(pathname)) {
      push('/login');
    } else if (status === 'authenticated' && PUBLIC_ROUTES.includes(pathname)) {
      push('/');
    }
  }, [status, push, pathname]);

  useEffect(() => {
    if (status !== 'authenticated' || !session?.user?.id || typeof window === 'undefined') return;

    OneSignal.init({
      appId: process.env.NEXT_PUBLIC_ONESIGNAL_APP_ID!,
      notifyButton: {
        enable: true,
        prenotify: true,
        showCredit: false,
        text: {
          "dialog.blocked.title": "Suscripción a Notificaciones",
          "dialog.blocked.message": "¿Quieres recibir notificaciones de recordatorios de medicamentos?",
          "dialog.main.button.subscribe": "Suscribirse",
          "dialog.main.button.unsubscribe": "Cancelar",
          "dialog.main.title": "Notificaciones de Recordatorios",
          "message.action.resubscribed": "¡Te has suscrito correctamente! Recibirás notificaciones de recordatorios.",
          "message.action.subscribed": "¡Te has suscrito correctamente! Recibirás notificaciones de recordatorios.",
          "message.action.unsubscribed": "Te has dado de baja de las notificaciones de recordatorios.",
          "tip.state.subscribed": "Estás suscrito a las notificaciones de recordatorios.",
          "tip.state.unsubscribed": "No estás suscrito a las notificaciones de recordatorios.",
          "message.prenotify": "Recibirás notificaciones de recordatorios de medicamentos",
          "tip.state.blocked": "Para recibir notificaciones de recordatorios, debes habilitar las notificaciones.",
          "message.action.subscribing": "Te estamos suscribiendo a las notificaciones de recordatorios.",
        }
      }
    }).then(() => {
      OneSignal.login(session.user.id);
    });
  }, [status, session?.user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {session && (
        <>
          {!sidebarOpen && <MobileMenuButton onClick={() => setSidebarOpen(true)} />}
          <SideBar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        </>
      )}
      <div className="flex-1 min-w-0 bg-blue-100">{children}</div>
    </>
  );
}
