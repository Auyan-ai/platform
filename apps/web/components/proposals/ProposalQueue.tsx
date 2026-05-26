'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useProposals, type Proposal, type ProposalStatus, type ProposalType } from '@/lib/api/hooks/proposals'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface ProposalQueueProps {
  tenantId: string
}

const STATUS_TABS: { label: string; value: ProposalStatus | 'all' }[] = [
  { label: 'Todas', value: 'all' },
  { label: 'Pendientes', value: 'pending' },
  { label: 'Aprobadas', value: 'approved' },
  { label: 'Rechazadas', value: 'rejected' },
  { label: 'Aplicadas', value: 'applied' },
]

const STATUS_VARIANT: Record<ProposalStatus, BadgeProps['variant']> = {
  pending: 'warning',
  approved: 'default',
  rejected: 'danger',
  applied: 'success',
}

const STATUS_LABEL: Record<ProposalStatus, string> = {
  pending: 'Pendiente',
  approved: 'Aprobada',
  rejected: 'Rechazada',
  applied: 'Aplicada',
}

const TYPE_LABEL: Record<ProposalType, string> = {
  aop_edit: 'Editar AOP',
  new_aop: 'Nuevo AOP',
  skill_request: 'Nueva skill',
  guardrail_addition: 'Guardrail',
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const colorClass =
    pct >= 80
      ? 'text-success-foreground'
      : pct >= 60
        ? 'text-warning-foreground'
        : 'text-danger-foreground'
  return <span className={`text-xs font-medium tabular-nums ${colorClass}`}>{pct}%</span>
}

function ProposalRow({ proposal, tenantId }: { proposal: Proposal; tenantId: string }) {
  return (
    <Link
      href={`/tenants/${tenantId}/proposals/${proposal.id}`}
      className="flex items-start gap-3 px-4 py-3 hover:bg-surface-muted transition-colors border-b border-border-subtle last:border-0"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs text-foreground-body font-mono">
            {TYPE_LABEL[proposal.proposal_type]}
          </span>
          {proposal.aop_slug && (
            <span className="text-xs text-foreground-muted">· {proposal.aop_slug}</span>
          )}
        </div>
        <p className="text-sm text-foreground-body line-clamp-2">{proposal.rationale}</p>
      </div>
      <div className="flex flex-col items-end gap-1 shrink-0">
        <Badge variant={STATUS_VARIANT[proposal.status]}>
          {STATUS_LABEL[proposal.status]}
        </Badge>
        <ConfidenceBadge value={proposal.judge_confidence} />
      </div>
    </Link>
  )
}

export function ProposalQueue({ tenantId }: ProposalQueueProps) {
  const [activeStatus, setActiveStatus] = useState<ProposalStatus | 'all'>('pending')

  const { data: proposals, isLoading, error } = useProposals(tenantId, {
    status: activeStatus === 'all' ? undefined : activeStatus,
    limit: 50,
  })

  return (
    <div className="rounded-md border border-border bg-surface overflow-hidden">
      <Tabs
        value={activeStatus}
        onValueChange={(v) => setActiveStatus(v as ProposalStatus | 'all')}
      >
        <TabsList className="w-full justify-start border-b border-border rounded-none">
          {STATUS_TABS.map(({ label, value }) => (
            <TabsTrigger key={value} value={value}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {isLoading ? (
        <div className="divide-y divide-border-subtle">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex gap-3 px-4 py-3">
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-4 w-full" />
              </div>
              <Skeleton className="h-5 w-16 rounded-xs" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground m-4">
          Error cargando propuestas
        </div>
      ) : !proposals?.length ? (
        <div className="px-4 py-10 text-sm text-foreground-muted text-center">
          No hay propuestas{activeStatus !== 'all' ? ` con status "${activeStatus}"` : ''}
        </div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {proposals.map((p) => (
            <ProposalRow key={p.id} proposal={p} tenantId={tenantId} />
          ))}
        </div>
      )}
    </div>
  )
}
