'use client'

import { useState } from 'react'

export function PoCToggle({ poc }: { poc: string }) {
  const [show, setShow] = useState(false)

  return (
    <div>
      <button
        type="button"
        onClick={() => setShow(!show)}
        className="text-xs text-muted-foreground hover:text-foreground underline"
      >
        {show ? 'Hide PoC' : 'Show PoC'}
      </button>
      {show && (
        <pre className="mt-2 rounded-md bg-destructive/5 border border-destructive/20 p-3 text-xs overflow-x-auto">{poc}</pre>
      )}
    </div>
  )
}
