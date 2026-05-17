'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

type Props = {
  label: string
  detail: Record<string, unknown> | null
  /** Si true, enmascara valores sensibles (email, phone, token, card) */
  maskPII?: boolean
}

const PII_KEYS = /email|phone|token|card|password|secret|key/i

function maskValue(value: unknown): unknown {
  if (typeof value === 'string') {
    if (value.includes('@')) return '•••@•••'
    if (value.length > 6) return value.slice(0, 3) + '•••'
    return '•••'
  }
  if (typeof value === 'object' && value !== null) {
    return maskObject(value as Record<string, unknown>)
  }
  return value
}

function maskObject(obj: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(obj).map(([k, v]) => {
      if (PII_KEYS.test(k)) return [k, maskValue(v)]
      if (typeof v === 'object' && v !== null) return [k, maskObject(v as Record<string, unknown>)]
      return [k, v]
    }),
  )
}

export function ToolCallChip({ label, detail, maskPII = false }: Props) {
  const [expanded, setExpanded] = useState(false)
  const hasDetail = detail && Object.keys(detail).length > 0
  const displayDetail = maskPII && detail ? maskObject(detail) : detail

  return (
    <div className="rounded border border-border bg-muted/40 text-xs font-mono">
      <button
        onClick={() => hasDetail && setExpanded((v) => !v)}
        className="flex w-full items-center gap-1 px-2 py-1 text-left"
        disabled={!hasDetail}
      >
        {hasDetail ? (
          expanded ? (
            <ChevronDown className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
          )
        ) : (
          <span className="w-3" />
        )}
        <span className="text-foreground">{label}</span>
      </button>
      {expanded && displayDetail && (
        <pre className="overflow-x-auto border-t border-border px-3 py-2 text-[10px] leading-relaxed text-muted-foreground">
          {JSON.stringify(displayDetail, null, 2)}
        </pre>
      )}
    </div>
  )
}
