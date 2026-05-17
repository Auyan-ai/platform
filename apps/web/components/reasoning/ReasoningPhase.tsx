import { Eye, GitBranch, MessageSquare } from 'lucide-react'
import { ReasoningItem } from './ReasoningItem'
import type { ReasoningEvent } from '@/lib/api/hooks/reasoning'

type Phase = ReasoningEvent['phase']

const PHASE_LABEL: Record<Phase, string> = {
  supervisor: 'Supervisors',
  decision: 'Decisions',
  response: 'Responses',
}

const PHASE_ICON: Record<Phase, React.ReactNode> = {
  supervisor: <Eye className="h-3.5 w-3.5" />,
  decision: <GitBranch className="h-3.5 w-3.5" />,
  response: <MessageSquare className="h-3.5 w-3.5" />,
}

type Props = {
  phase: Phase
  events: ReasoningEvent[]
  maskPII?: boolean
}

export function ReasoningPhase({ phase, events, maskPII }: Props) {
  if (events.length === 0) return null

  const allDone = events.every((e) => e.status !== 'pending')

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {PHASE_ICON[phase]}
        <span>{PHASE_LABEL[phase]}</span>
        {allDone && (
          <span className="ml-auto text-green-500 text-[10px]">✓</span>
        )}
      </div>
      <div className="ml-5 flex flex-col">
        {events.map((event) => (
          <ReasoningItem key={event.id} event={event} maskPII={maskPII} />
        ))}
      </div>
    </div>
  )
}
