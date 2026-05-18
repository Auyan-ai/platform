'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import {
  useProposal,
  useApproveProposal,
  useRejectProposal,
  type ProposalStatus,
  type ProposalType,
} from '@/lib/api/hooks/proposals'

interface ProposalDetailProps {
  tenantId: string
  proposalId: string
}

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

export function ProposalDetail({ tenantId, proposalId }: ProposalDetailProps) {
  const router = useRouter()
  const { data: proposal, isLoading, error } = useProposal(tenantId, proposalId)
  const approveMut = useApproveProposal(tenantId)
  const rejectMut = useRejectProposal(tenantId)

  const [rejectComment, setRejectComment] = useState('')
  const [showRejectForm, setShowRejectForm] = useState(false)

  async function handleApprove() {
    if (!proposal) return
    try {
      const result = await approveMut.mutateAsync(proposalId)
      router.push(`/tenants/${tenantId}/aops/${result.aop_id}`)
    } catch {
      // error shown inline
    }
  }

  async function handleReject() {
    try {
      await rejectMut.mutateAsync({ proposalId, comment: rejectComment || undefined })
      setShowRejectForm(false)
      router.back()
    } catch {
      // error shown inline
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-6 w-48 bg-neutral-100 rounded" />
        <div className="h-32 w-full bg-neutral-100 rounded" />
        <div className="h-24 w-full bg-neutral-100 rounded" />
      </div>
    )
  }

  if (error || !proposal) {
    return (
      <div className="text-sm text-red-500">
        {error?.message ?? 'Propuesta no encontrada'}
      </div>
    )
  }

  const isPending = proposal.status === 'pending'

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-neutral-500 font-mono">
              {TYPE_LABEL[proposal.proposal_type]}
            </span>
            {proposal.aop_slug && (
              <span className="text-xs text-neutral-400">· {proposal.aop_slug}</span>
            )}
          </div>
          <p className="text-xs text-neutral-400 font-mono">{proposal.id}</p>
        </div>
        <span
          className={cn(
            'inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium shrink-0',
            STATUS_BADGE[proposal.status],
          )}
        >
          {STATUS_LABEL[proposal.status]}
        </span>
      </div>

      {/* Rationale */}
      <section>
        <h2 className="text-sm font-semibold text-neutral-700 mb-2">Razonamiento del juez</h2>
        <p className="text-sm text-neutral-700 leading-relaxed bg-neutral-50 rounded-lg px-4 py-3 border border-neutral-200">
          {proposal.rationale}
        </p>
      </section>

      {/* Diff */}
      <section>
        <h2 className="text-sm font-semibold text-neutral-700 mb-2">Cambio propuesto</h2>
        <div className="rounded-lg border border-neutral-200 bg-white overflow-hidden">
          <pre className="text-sm font-mono text-neutral-700 p-4 whitespace-pre-wrap leading-relaxed">
            {proposal.diff_markdown}
          </pre>
        </div>
      </section>

      {/* Metadata */}
      <section className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
          <p className="text-xs text-neutral-400 mb-0.5">Confianza</p>
          <p className="font-semibold tabular-nums">
            {Math.round(proposal.judge_confidence * 100)}%
          </p>
        </div>
        <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
          <p className="text-xs text-neutral-400 mb-0.5">Modelo juez</p>
          <p className="font-mono text-xs">{proposal.judge_model_used}</p>
        </div>
        <div className="rounded-lg border border-neutral-200 bg-white px-3 py-2">
          <p className="text-xs text-neutral-400 mb-0.5">Conversaciones</p>
          <p className="font-semibold">{proposal.evidence_conversations.length}</p>
        </div>
      </section>

      {/* Review info if already reviewed */}
      {proposal.reviewed_at && (
        <section className="rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-3 text-sm text-neutral-600">
          Revisada el{' '}
          {new Date(proposal.reviewed_at).toLocaleString('es-VE', {
            day: 'numeric',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          })}
          {proposal.review_comment && (
            <p className="mt-1 text-neutral-500 italic">"{proposal.review_comment}"</p>
          )}
        </section>
      )}

      {/* Actions */}
      {isPending && (
        <section className="flex flex-col gap-3">
          <div className="flex gap-2">
            <button
              onClick={handleApprove}
              disabled={approveMut.isPending}
              className="flex-1 rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 transition-colors disabled:opacity-50"
            >
              {approveMut.isPending ? 'Aprobando…' : 'Aprobar y abrir editor'}
            </button>
            <button
              onClick={() => setShowRejectForm((v) => !v)}
              disabled={rejectMut.isPending}
              className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 transition-colors disabled:opacity-50"
            >
              Rechazar
            </button>
          </div>

          {approveMut.error && (
            <p className="text-xs text-red-500">{approveMut.error.message}</p>
          )}

          {showRejectForm && (
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 space-y-3">
              <textarea
                value={rejectComment}
                onChange={(e) => setRejectComment(e.target.value)}
                placeholder="Razón del rechazo (opcional)"
                rows={3}
                className="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-neutral-900"
              />
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowRejectForm(false)}
                  className="px-3 py-1.5 text-sm text-neutral-600 hover:text-neutral-900"
                >
                  Cancelar
                </button>
                <button
                  onClick={handleReject}
                  disabled={rejectMut.isPending}
                  className="rounded-lg bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-500 transition-colors disabled:opacity-50"
                >
                  {rejectMut.isPending ? 'Rechazando…' : 'Confirmar rechazo'}
                </button>
              </div>
              {rejectMut.error && (
                <p className="text-xs text-red-500">{rejectMut.error.message}</p>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
