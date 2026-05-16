'use client'

import { useState } from 'react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { useEscalations, useClaimMutation, useResolveMutation } from '@/lib/api/hooks/escalations'
import type { EscalationStatus } from '@auyan/shared'
import type { components } from '@auyan/shared/api-types'

type EscalationOut = components['schemas']['EscalationOut']

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

const STATUS_STYLES: Record<EscalationStatus, string> = {
  pending: 'bg-yellow-50 text-yellow-700',
  claimed: 'bg-blue-50 text-blue-700',
  resolved: 'bg-neutral-100 text-neutral-500',
}

const STATUS_LABELS: Record<EscalationStatus, string> = {
  pending: 'Pendiente',
  claimed: 'En atención',
  resolved: 'Resuelta',
}

const STATUS_FILTERS: Array<EscalationStatus | 'all'> = ['all', 'pending', 'claimed', 'resolved']

const FILTER_LABELS: Record<EscalationStatus | 'all', string> = {
  all: 'Todas',
  pending: 'Pendientes',
  claimed: 'En atención',
  resolved: 'Resueltas',
}

function relativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'ahora'
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

// ----------------------------------------------------------------
// Row
// ----------------------------------------------------------------

function EscalationRow({
  esc,
  conversationBasePath,
  onClaim,
  onResolve,
  isActing,
  readOnly,
}: {
  esc: EscalationOut
  conversationBasePath: string
  onClaim: (id: string) => void
  onResolve: (id: string) => void
  isActing: boolean
  readOnly: boolean
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3 hover:bg-neutral-50 transition-colors">
      {/* Status badge */}
      <span
        className={cn(
          'mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-xs font-medium',
          STATUS_STYLES[esc.status],
        )}
      >
        {STATUS_LABELS[esc.status]}
      </span>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-neutral-800 line-clamp-2">{esc.reason}</p>
        <div className="mt-1 flex items-center gap-2 text-xs text-neutral-400">
          <Link
            href={`${conversationBasePath}/${esc.conversation_id}`}
            className="hover:text-neutral-700 underline underline-offset-2"
          >
            Ver conversación
          </Link>
          <span>·</span>
          <span>{relativeTime(esc.created_at)}</span>
        </div>
      </div>

      {/* Actions — ocultos en modo read-only */}
      {!readOnly && (
        <div className="shrink-0 flex gap-2">
          {esc.status === 'pending' && (
            <button
              onClick={() => onClaim(esc.id)}
              disabled={isActing}
              className="px-3 py-1 rounded-lg bg-neutral-900 text-white text-xs font-medium hover:bg-neutral-700 disabled:opacity-40"
            >
              Tomar
            </button>
          )}
          {esc.status === 'claimed' && (
            <button
              onClick={() => onResolve(esc.id)}
              disabled={isActing}
              className="px-3 py-1 rounded-lg bg-green-600 text-white text-xs font-medium hover:bg-green-700 disabled:opacity-40"
            >
              Resolver
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ----------------------------------------------------------------
// Main component
// ----------------------------------------------------------------

const LIMIT = 50

export function EscalationQueue({
  tenantId,
  readOnly = false,
  conversationBasePath,
}: {
  tenantId: string
  readOnly?: boolean
  conversationBasePath?: string
}) {
  const [activeStatus, setActiveStatus] = useState<EscalationStatus | 'all'>('pending')
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const status = activeStatus === 'all' ? undefined : activeStatus

  const { data, isLoading, isError, error: queryError } = useEscalations({
    tenantId,
    status,
    limit: LIMIT,
    offset,
  })

  const claimMutation = useClaimMutation(tenantId)
  const resolveMutation = useResolveMutation(tenantId)
  const isActing = claimMutation.isPending || resolveMutation.isPending

  const escalations = data?.escalations ?? []
  const hasMore = escalations.length === LIMIT
  const resolvedConvBasePath =
    conversationBasePath ?? `/tenants/${tenantId}/conversations`

  async function handleClaim(id: string) {
    setError(null)
    try {
      await claimMutation.mutateAsync(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al tomar la escalación')
    }
  }

  async function handleResolve(id: string) {
    setError(null)
    try {
      await resolveMutation.mutateAsync(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al resolver la escalación')
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-neutral-900">Escalaciones</h1>
        {isLoading && <span className="text-xs text-neutral-400">Actualizando...</span>}
      </div>

      {/* Filtros */}
      <div className="flex gap-1 border-b border-neutral-200 pb-0">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => { setActiveStatus(s); setOffset(0) }}
            className={cn(
              'px-3 py-2 text-sm font-medium transition-colors -mb-px border-b-2',
              activeStatus === s
                ? 'border-neutral-900 text-neutral-900'
                : 'border-transparent text-neutral-500 hover:text-neutral-700',
            )}
          >
            {FILTER_LABELS[s]}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {/* Lista */}
      {isError ? (
        <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          Error al cargar: {queryError instanceof Error ? queryError.message : 'desconocido'}
        </div>
      ) : escalations.length === 0 && !isLoading ? (
        <div className="py-12 text-center text-sm text-neutral-400">
          No hay escalaciones {activeStatus !== 'all' && `con estado "${FILTER_LABELS[activeStatus]}"`}.
        </div>
      ) : (
        <div className="divide-y divide-neutral-100 rounded-xl border border-neutral-200 bg-white">
          {escalations.map((esc) => (
            <EscalationRow
              key={esc.id}
              esc={esc}
              conversationBasePath={resolvedConvBasePath}
              onClaim={handleClaim}
              onResolve={handleResolve}
              isActing={isActing}
              readOnly={readOnly}
            />
          ))}
        </div>
      )}

      {/* Paginación */}
      {(offset > 0 || hasMore) && (
        <div className="flex justify-between">
          <button
            onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
            disabled={offset === 0}
            className="text-sm text-neutral-500 hover:text-neutral-900 disabled:opacity-30"
          >
            ← Anterior
          </button>
          <button
            onClick={() => setOffset((o) => o + LIMIT)}
            disabled={!hasMore}
            className="text-sm text-neutral-500 hover:text-neutral-900 disabled:opacity-30"
          >
            Siguiente →
          </button>
        </div>
      )}
    </div>
  )
}
