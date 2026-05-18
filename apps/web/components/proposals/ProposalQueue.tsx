'use client'

import Link from 'next/link'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { useProposals, type Proposal, type ProposalStatus, type ProposalType } from '@/lib/api/hooks/proposals'

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

const STATUS_BADGE: Record<ProposalStatus, string> = {
  pending: 'bg-amber-50 text-amber-700 border-amber-200',
  approved: 'bg-blue-50 text-blue-700 border-blue-200',
  rejected: 'bg-red-50 text-red-700 border-red-200',
  applied: 'bg-emerald-50 text-emerald-700 border-emerald-200',
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
  const color =
    pct >= 80 ? 'text-emerald-600' : pct >= 60 ? 'text-amber-600' : 'text-red-500'
  return <span className={`text-xs font-medium tabular-nums ${color}`}>{pct}%</span>
}

function ProposalRow({ proposal, tenantId }: { proposal: Proposal; tenantId: string }) {
  return (
    <Link
      href={`/tenants/${tenantId}/proposals/${proposal.id}`}
      className="flex items-start gap-3 px-4 py-3 hover:bg-neutral-50 transition-colors border-b border-neutral-100 last:border-0"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs text-neutral-500 font-mono">
            {TYPE_LABEL[proposal.proposal_type]}
          </span>
          {proposal.aop_slug && (
            <span className="text-xs text-neutral-400">· {proposal.aop_slug}</span>
          )}
        </div>
        <p className="text-sm text-neutral-800 line-clamp-2">{proposal.rationale}</p>
      </div>
      <div className="flex flex-col items-end gap-1 shrink-0">
        <span
          className={cn(
            'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
            STATUS_BADGE[proposal.status],
          )}
        >
          {STATUS_LABEL[proposal.status]}
        </span>
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
    <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden">
      {/* Tabs */}
      <div className="flex border-b border-neutral-200 overflow-x-auto">
        {STATUS_TABS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => setActiveStatus(value)}
            className={cn(
              'shrink-0 px-4 py-2.5 text-sm font-medium transition-colors border-b-2',
              activeStatus === value
                ? 'border-neutral-900 text-neutral-900'
                : 'border-transparent text-neutral-500 hover:text-neutral-700',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="divide-y divide-neutral-100">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex gap-3 px-4 py-3 animate-pulse">
              <div className="flex-1">
                <div className="h-3 w-24 bg-neutral-100 rounded mb-2" />
                <div className="h-4 w-full bg-neutral-100 rounded" />
              </div>
              <div className="h-5 w-16 bg-neutral-100 rounded-full" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="px-4 py-6 text-sm text-red-500 text-center">
          Error cargando propuestas
        </div>
      ) : !proposals?.length ? (
        <div className="px-4 py-10 text-sm text-neutral-400 text-center">
          No hay propuestas{activeStatus !== 'all' ? ` con status "${activeStatus}"` : ''}
        </div>
      ) : (
        <div className="divide-y divide-neutral-100">
          {proposals.map((p) => (
            <ProposalRow key={p.id} proposal={p} tenantId={tenantId} />
          ))}
        </div>
      )}
    </div>
  )
}
