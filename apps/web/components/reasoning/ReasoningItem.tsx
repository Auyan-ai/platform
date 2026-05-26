'use client'

import { Check, Clock, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ToolCallChip } from './ToolCallChip'
import type { ReasoningEvent } from '@/lib/api/hooks/reasoning'

type Props = {
  event: ReasoningEvent
  maskPII?: boolean
}

function StatusIcon({ status }: { status: ReasoningEvent['status'] }) {
  if (status === 'done') return <Check className="h-3.5 w-3.5 text-success" />
  if (status === 'error') return <X className="h-3.5 w-3.5 text-danger" />
  return <Clock className="h-3.5 w-3.5 animate-pulse text-foreground-muted" />
}

export function ReasoningItem({ event, maskPII }: Props) {
  const isToolEvent =
    event.event_type === 'tool_call' || event.event_type === 'tool_result'

  return (
    <div
      className={cn(
        'flex flex-col gap-1 py-1',
        event.status === 'error' && 'opacity-70',
      )}
    >
      <div className="flex items-center gap-2">
        <StatusIcon status={event.status} />
        {isToolEvent ? (
          <ToolCallChip
            label={event.label}
            detail={event.detail}
            maskPII={maskPII}
          />
        ) : (
          <span className="text-xs text-foreground">{event.label}</span>
        )}
      </div>
    </div>
  )
}
