import { withAuth } from 'next-auth/middleware'
import { NextResponse } from 'next/server'

const GUEST_ONLY_ROUTES = ['/login', '/register']

export default withAuth(
  function middleware(req) {
    const { pathname } = req.nextUrl
    if (req.nextauth.token && GUEST_ONLY_ROUTES.includes(pathname)) {
      return NextResponse.redirect(new URL('/', req.url))
    }
    return NextResponse.next()
  },
  {
    pages: { signIn: '/login' },
    callbacks: {
      authorized: ({ token, req }) => {
        const { pathname } = req.nextUrl
        if (GUEST_ONLY_ROUTES.includes(pathname)) return true
        return !!token
      },
    },
  }
)

export const config = {
  matcher: [
    '/((?!api/auth|_next/static|_next/image|favicon\\.ico|OneSignalSDKWorker\\.js|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
