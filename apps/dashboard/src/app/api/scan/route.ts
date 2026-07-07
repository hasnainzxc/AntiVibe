import { NextRequest, NextResponse } from 'next/server'

const SANDBOX_URL = process.env.SANDBOX_SVC_URL || 'http://localhost:8080'

export async function POST(req: NextRequest) {
  try {
    const { repo_url } = await req.json()
    if (!repo_url) {
      return NextResponse.json({ error: 'repo_url required' }, { status: 400 })
    }

    const res = await fetch(`${SANDBOX_URL}/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url }),
    })

    if (!res.ok) {
      const text = await res.text()
      return NextResponse.json({ error: text }, { status: res.status })
    }

    const data = await res.json()
    return NextResponse.json(data)
  } catch (err) {
    console.error('scan proxy error', err)
    return NextResponse.json({ error: 'Failed to reach sandbox service' }, { status: 502 })
  }
}

export async function GET(req: NextRequest) {
  const scanId = req.nextUrl.searchParams.get('scan_id')
  if (!scanId) {
    return NextResponse.json({ error: 'scan_id required' }, { status: 400 })
  }

  try {
    const res = await fetch(`${SANDBOX_URL}/scan/${scanId}`)
    if (!res.ok) {
      if (res.status === 404) {
        return NextResponse.json({ status: 'pending' })
      }
      const text = await res.text()
      return NextResponse.json({ error: text }, { status: res.status })
    }

    const data = await res.json()
    return NextResponse.json(data)
  } catch (err) {
    console.error('scan status proxy error', err)
    return NextResponse.json({ error: 'Failed to reach sandbox service' }, { status: 502 })
  }
}
