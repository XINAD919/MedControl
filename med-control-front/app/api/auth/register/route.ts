import { NextRequest, NextResponse } from 'next/server'

const API_INTERNAL = process.env.API_INTERNAL_URL ?? 'http://localhost:8000'
const AUTH_SECRET_INTERNAL = process.env.AUTH_SECRET_INTERNAL ?? ''

export async function POST(req: NextRequest) {
  const body = await req.json()

  const res = await fetch(`${API_INTERNAL}/api/auth/register`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Auth-Secret': AUTH_SECRET_INTERNAL,
    },
    body: JSON.stringify(body),
  })

  const data = await res.json().catch(() => ({}))
  return NextResponse.json(data, { status: res.status })
}
