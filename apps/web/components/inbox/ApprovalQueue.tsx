'use client'

import { useState } from 'react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import {
  useApprovals,
  useApproveMutation,
  useRejectMutation,
} from '@/lib/api/hooks/approvals'
import type { ApprovalStatus, ApprovalOut } from '@/lib/api/hooks/approvals'

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

const STATUS_STYLES: Record<ApprovalStatus, string> = {
  pending: 'bg-amber-50 text-amber-700',
  approved: 'bg-green-50 text-green-700',
  rejected: 'bg-red-50 text-red-700',
}

const STATUS_LABELS: Record<ApprovalStatus, string> = {
  pending: 'Pendiente',
  approved: 'Aprobada',
  rejected: 'Rechazada',
}

const STATUS_FILTERS: Array<ApprovalStatus | 'all'> = ['pending', 'approved', 'rejected', 'all']

const FILTER_LABELS: Record<ApprovalStatus | 'all', string> = {
  all: 'Todas',
  pending: 'Pendientes',
  approved: 'Aprobadas',
  rejected: 'Rechazadas',
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

function formatInputs(inputs: Record<string, unknown>): string {
  return Object.entries(inputs)
    .map(([k, v]) => `${k}: ${v}`)
    .join(' · ')
}

// ----------------------------------------------------------------
// Reject modal
// ----------------------------------------------------------------

function RejectModal({
  onConfirm,
  onCancel,
  isPending,
}: {
  onConfirm: (comment: string) => void
  onCancel: () => void
  isPending: boolean
}) {
  const [comment, setComment] = useState('')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-base font-semibold text-neutral-900">Rechazar acción</h2>
        <p className="mt-1 text-sm text-neutral-500">Indica el motivo del rechazo.</p>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Motivo del rechazo..."
          rows={3}
          className="mt-3 w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-neutral-900"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={isPending}
            className="rounded-lg px-4 py-2 text-sm text-neutral-600 hover:bg-neutral-100 disabled:opacity-40"
          >
            Cancelar
          </button>
          <button
            onClick={() => comment.trim() && onConfirm(comment.trim())}
            disabled={isPending || !comment.trim()}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-40"
          >
            {isPending ? 'Rechazando...' : 'Rechazar'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ----------------------------------------------------------------
// Row
// ----------------------------------------------------------------

function ApprovalRow({
  approval,
  tenantId,
  onApprove,
  onReject,
  isActing,
}: {
  approval: ApprovalOut
  tenantId: string
  onApprove: (id: string) => void
  onReject: (id: string) => void
  isActing: boolean
}) {
  const isPending = approval.status === 'pending'
  return (
    <div className="px-4 py-3 hover:bg-neutral-50 transition-colors">
      <div className="flex items-start gap-3">
        {/* Status badge */}
        <span
          className={cn(
            'mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-xs font-medium',
            STATUS_STYLES[approval.status],
          )}
        >
          {STATUS_LABELS[approval.status]}
        </span>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-neutral-800">{approval.skill_slug}</p>
          <p className="mt-0.5 text-xs text-neutral-500 truncate">
            {formatInputs(approval.inputs_redacted)}
          </p>
          <div className="mt-1 flex items-center gap-2 text-xs text-neutral-400">
            <Link
              href={`/tenants/${tenantId}/conversations/${approval.conversation_id}`}
              className="hover:text-neutral-700 underline underline-offset-2"
            >
              Ver conversación
            </Link>
            <span>·</span>
            <span>AOP: {approval.aop_slug} v{approval.aop_version}</span>
            <span>·</span>
            <span>{relativeTime(approval.created_at)}</span>
          </div>
          {approval.review_comment && (
            <p className="mt-1 text-xs text-neutral-400 italic">
              &ldquo;{approval.review_comment}&rdquo;
            </p>
          )}
        </div>

        {/* Actions */}
        {isPending && (
          <div className="shrink-0 flex gap-2">
            <button
              onClick={() => onApprove(approval.id)}
              disabled={isActing}
              className="px-3 py-1 rounded-lg bg-green-600 text-white text-xs font-medium hover:bg-green-700 disabled:opacity-40"
            >
              Aprobar
            </button>
            <button
              onClick={() => onReject(approval.id)}
              disabled={isActing}
              className="px-3 py-1 rounded-lg bg-red-100 text-red-700 text-xs font-medium hover:bg-red-200 disabled:opacity-40"
            >
              Rechazar
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ----------------------------------------------------------------
// Main component
// ----------------------------------------------------------------

const LIMIT = 50

export function ApprovalQueue({ tenantId }: { tenantId: string }) {
  const [activeStatus, setActiveStatus] = useState<ApprovalStatus | 'all'>('pending')
  const [offset, setOffset] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)

  const status = activeStatus === 'all' ? undefined : activeStatus

  const { data, isLoading, isError, error: queryError } = useApprovals({
    tenantId,
    status,
    limit: LIMIT,
    offset,
  })

  const approveMutation = useApproveMutation(tenantId)
  const rejectMutation = useRejectMutation(tenantId)
  const isActing = approveMutation.isPending || rejectMutation.isPending

  const approvals = data?.approvals ?? []
  const hasMore = approvals.length === LIMIT

  async function handleApprove(id: string) {
    setActionError(null)
    try {
      await approveMutation.mutateAsync({ approvalId: id })
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Error al aprobar')
    }
  }

  async function handleRejectConfirm(comment: string) {
    if (!rejectingId) return
    setActionError(null)
    try {
      await rejectMutation.mutateAsync({ approvalId: rejectingId, comment })
      setRejectingId(null)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Error al rechazar')
    }
  }

  return (
    <>
      {rejectingId && (
        <RejectModal
          onConfirm={handleRejectConfirm}
          onCancel={() => setRejectingId(null)}
          isPending={rejectMutation.isPending}
        />
      )}

      <div className="space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-neutral-900">Aprobaciones</h1>
          {isLoading && <span className="text-xs text-neutral-400">Actualizando...</span>}
        </div>

        {/* Filters */}
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

        {actionError && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{actionError}</div>
        )}

        {/* List */}
        {isError ? (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            Error al cargar:{' '}
            {queryError instanceof Error ? queryError.message : 'desconocido'}
          </div>
        ) : approvals.length === 0 && !isLoading ? (
          <div className="py-12 text-center text-sm text-neutral-400">
            No hay aprobaciones{' '}
            {activeStatus !== 'all' && `con estado "${FILTER_LABELS[activeStatus]}"`}.
          </div>
        ) : (
          <div className="divide-y divide-neutral-100 rounded-xl border border-neutral-200 bg-white">
            {approvals.map((a) => (
              <ApprovalRow
                key={a.id}
                approval={a}
                tenantId={tenantId}
                onApprove={handleApprove}
                onReject={setRejectingId}
                isActing={isActing}
              />
            ))}
          </div>
        )}

        {/* Pagination */}
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
    </>
  )
}
