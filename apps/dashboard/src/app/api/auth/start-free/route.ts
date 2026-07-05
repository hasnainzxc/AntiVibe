import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export async function POST(request: NextRequest) {
  const body = await request.json()
  const { email } = body as { email?: string }

  if (!email || typeof email !== 'string') {
    return NextResponse.json({ error: 'Email is required' }, { status: 400 })
  }

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailRegex.test(email)) {
    return NextResponse.json({ error: 'Invalid email' }, { status: 400 })
  }

  // TODO: send magic link email when email service is configured
  // For now, log the signup request
  console.log('free tier signup', { email })

  // TODO: create verification token and store in DB
  // const token = crypto.randomUUID()
  // await db.verification_tokens.create({ email, token, expires_at: ... })

  return NextResponse.json({
    success: true,
    message: 'Check your email for a magic link to start your free scans.',
  })
}
