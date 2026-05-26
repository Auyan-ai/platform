'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useEscalations, useClaimMutation, useResolveMutation } from '@/lib/api/hooks/escalations'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { EscalationStatus } from '@auyan/shared'
import type { components } from '@auyan/shared/api-types'

type EscalationOut = components['schemas']['EscalationOut']

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

const STATUS_VARIANT: Record<EscalationStatus, BadgeProps['variant']> = {
  pending: 'warning',
  claimed: 'default',
  resolved: 'muted',
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
    <div className="flex items-start gap-3 px-4 py-3 hover:bg-surface-muted transition-colors">
      <Badge variant={STATUS_VARIANT[esc.status]} className="mt-0.5">
        {STATUS_LABELS[esc.status]}
      </Badge>

      <div className="flex-1 min-w-0">
        <p className="text-sm text-foreground-body line-clamp-2">{esc.reason}</p>
        <div className="mt-1 flex items-center gap-2 text-xs text-foreground-muted">
          <Link
            href={`${conversationBasePath}/${esc.conversation_id}`}
            className="text-accent-foreground hover:underline underline-offset-2"
          >
            Ver conversación
          </Link>
          <span>·</span>
          <span className="tabular-nums">{relativeTime(esc.created_at)}</span>
        </div>
      </div>

      {!readOnly && (
        <div className="shrink-0 flex gap-2">
          {esc.status === 'pending' && (
            <Button size="sm" onClick={() => onClaim(esc.id)} disabled={isActing}>
              Tomar
            </Button>
          )}
          {esc.status === 'claimed' && (
            <Button
              size="sm"
              onClick={() => onResolve(esc.id)}
              disabled={isActing}
              className="bg-success text-foreground-on-accent hover:bg-success-700"
            >
              Resolver
            </Button>
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
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-foreground">Escalaciones</h1>
        {isLoading && (
          <span className="text-xs text-foreground-muted">Actualizando…</span>
        )}
      </div>

      <Tabs
        value={activeStatus}
        onValueChange={(v) => {
          setActiveStatus(v as EscalationStatus | 'all')
          setOffset(0)
        }}
      >
        <TabsList className="w-full justify-start">
          {STATUS_FILTERS.map((s) => (
            <TabsTrigger key={s} value={s}>
              {FILTER_LABELS[s]}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {error && (
        <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
          {error}
        </div>
      )}

      {isError ? (
        <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
          Error al cargar: {queryError instanceof Error ? queryError.message : 'desconocido'}
        </div>
      ) : escalations.length === 0 && !isLoading ? (
        <div className="py-12 text-center text-sm text-foreground-muted">
          No hay escalaciones{' '}
          {activeStatus !== 'all' && `con estado "${FILTER_LABELS[activeStatus]}"`}.
        </div>
      ) : (
        <div className="divide-y divide-border-subtle rounded-md border border-border bg-surface">
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

      {(offset > 0 || hasMore) && (
        <div className="flex justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
            disabled={offset === 0}
          >
            ← Anterior
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOffset((o) => o + LIMIT)}
            disabled={!hasMore}
          >
            Siguiente →
          </Button>
        </div>
      )}
    </div>
  )
}
