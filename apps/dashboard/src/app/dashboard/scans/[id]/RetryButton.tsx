'use client'

import { Button } from '@/components/ui/button'

export function RetryButton() {
  return (
    <Button variant="outline" onClick={() => window.location.reload()}>
      Retry
    </Button>
  )
}
