'use client'

import { useState } from 'react'
import { Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'

const features = [
  '20 scans per month',
  'Static analysis + sandbox + fuzz (3 tiers)',
  'Auto-generated fix PRs',
  'Email support',
  'Public & private repos',
]

export function PricingCard() {
  const [loading, setLoading] = useState(false)

  async function handleSubscribe() {
    setLoading(true)
    try {
      const res = await fetch('/api/stripe/checkout', { method: 'POST' })
      const data = await res.json()
      if (data.url) {
        window.location.href = data.url
      }
    } catch {
      setLoading(false)
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle className="text-xl">Pro</CardTitle>
        <CardDescription>For teams and serious projects</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="flex items-baseline gap-1">
          <span className="text-3xl font-bold">$29</span>
          <span className="text-sm text-muted-foreground">/month</span>
        </div>
        <ul className="grid gap-2 text-sm">
          {features.map((f) => (
            <li key={f} className="flex items-center gap-2">
              <Check className="size-4 text-emerald-500 shrink-0" />
              <span>{f}</span>
            </li>
          ))}
        </ul>
      </CardContent>
      <CardFooter>
        <Button
          className="w-full"
          onClick={handleSubscribe}
          disabled={loading}
        >
          {loading ? 'Redirecting...' : 'Subscribe'}
        </Button>
      </CardFooter>
    </Card>
  )
}
