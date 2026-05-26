'use client'

import { useProposalMetrics } from '@/lib/api/hooks/proposals'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

interface ProposalMetricsProps {
  tenantId: string
}

export function ProposalMetrics({ tenantId }: ProposalMetricsProps) {
  const { data, isLoading } = useProposalMetrics(tenantId)

  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} className="p-4 space-y-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-6 w-12" />
          </Card>
        ))}
      </div>
    )
  }

  const stats = [
    {
      label: 'Pendientes',
      value: data.pending,
      tone: 'text-warning-foreground',
    },
    {
      label: 'Aceptación',
      value:
        data.acceptance_rate !== null
          ? `${(data.acceptance_rate * 100).toFixed(0)}%`
          : '—',
      tone: 'text-success-foreground',
    },
    {
      label: 'Costo total',
      value: `$${data.cost_usd_total.toFixed(3)}`,
      tone: 'text-foreground',
    },
    {
      label: 'Costo / aprobada',
      value:
        data.cost_per_accepted_proposal !== null
          ? `$${data.cost_per_accepted_proposal.toFixed(3)}`
          : '—',
      tone: 'text-foreground',
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map(({ label, value, tone }) => (
        <Card key={label} className="p-4">
          <p className="text-xs text-foreground-muted mb-1">{label}</p>
          <p className={`text-xl font-semibold tabular-nums ${tone}`}>{value}</p>
        </Card>
      ))}
    </div>
  )
}
