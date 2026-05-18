'use client'

import { useProposalMetrics } from '@/lib/api/hooks/proposals'

interface ProposalMetricsProps {
  tenantId: string
}

export function ProposalMetrics({ tenantId }: ProposalMetricsProps) {
  const { data, isLoading } = useProposalMetrics(tenantId)

  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-neutral-200 bg-white p-4 animate-pulse">
            <div className="h-3 w-20 bg-neutral-100 rounded mb-2" />
            <div className="h-6 w-12 bg-neutral-100 rounded" />
          </div>
        ))}
      </div>
    )
  }

  const stats = [
    {
      label: 'Pendientes',
      value: data.pending,
      color: 'text-amber-600',
    },
    {
      label: 'Aceptación',
      value:
        data.acceptance_rate !== null
          ? `${(data.acceptance_rate * 100).toFixed(0)}%`
          : '—',
      color: 'text-emerald-600',
    },
    {
      label: 'Costo total',
      value: `$${data.cost_usd_total.toFixed(3)}`,
      color: 'text-neutral-700',
    },
    {
      label: 'Costo / aprobada',
      value:
        data.cost_per_accepted_proposal !== null
          ? `$${data.cost_per_accepted_proposal.toFixed(3)}`
          : '—',
      color: 'text-neutral-700',
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map(({ label, value, color }) => (
        <div
          key={label}
          className="rounded-xl border border-neutral-200 bg-white p-4"
        >
          <p className="text-xs text-neutral-500 mb-1">{label}</p>
          <p className={`text-xl font-semibold tabular-nums ${color}`}>{value}</p>
        </div>
      ))}
    </div>
  )
}
