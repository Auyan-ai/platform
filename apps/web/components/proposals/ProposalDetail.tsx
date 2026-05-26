'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import {
  useProposal,
  useApproveProposal,
  useRejectProposal,
  type ProposalStatus,
  type ProposalType,
} from '@/lib/api/hooks/proposals'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'

interface ProposalDetailProps {
  tenantId: string
  proposalId: string
}

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
      <div className="space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  if (error || !proposal) {
    return (
      <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        {error?.message ?? 'Propuesta no encontrada'}
      </div>
    )
  }

  const isPending = proposal.status === 'pending'

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-foreground-body font-mono">
              {TYPE_LABEL[proposal.proposal_type]}
            </span>
            {proposal.aop_slug && (
              <span className="text-xs text-foreground-muted">· {proposal.aop_slug}</span>
            )}
          </div>
          <p className="text-xs text-foreground-muted font-mono">{proposal.id}</p>
        </div>
        <Badge variant={STATUS_VARIANT[proposal.status]} className="shrink-0 py-1">
          {STATUS_LABEL[proposal.status]}
        </Badge>
      </div>

      <section>
        <h2 className="text-sm font-semibold text-foreground-body mb-2">Razonamiento del juez</h2>
        <Card className="bg-surface-muted px-4 py-3">
          <p className="text-sm text-foreground-body leading-relaxed">{proposal.rationale}</p>
        </Card>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground-body mb-2">Cambio propuesto</h2>
        <Card className="overflow-hidden">
          <pre className="text-sm font-mono text-foreground-body p-4 whitespace-pre-wrap leading-relaxed">
            {proposal.diff_markdown}
          </pre>
        </Card>
      </section>

      <section className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <Card className="px-3 py-2">
          <p className="text-xs text-foreground-muted mb-0.5">Confianza</p>
          <p className="font-semibold tabular-nums text-foreground">
            {Math.round(proposal.judge_confidence * 100)}%
          </p>
        </Card>
        <Card className="px-3 py-2">
          <p className="text-xs text-foreground-muted mb-0.5">Modelo juez</p>
          <p className="font-mono text-xs text-foreground">{proposal.judge_model_used}</p>
        </Card>
        <Card className="px-3 py-2">
          <p className="text-xs text-foreground-muted mb-0.5">Conversaciones</p>
          <p className="font-semibold text-foreground tabular-nums">
            {proposal.evidence_conversations.length}
          </p>
        </Card>
      </section>

      {proposal.reviewed_at && (
        <Card className="bg-surface-muted px-4 py-3 text-sm text-foreground-body">
          Revisada el{' '}
          <span className="tabular-nums">
            {new Date(proposal.reviewed_at).toLocaleString('es-VE', {
              day: 'numeric',
              month: 'short',
              year: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
          {proposal.review_comment && (
            <p className="mt-1 text-foreground-muted italic">"{proposal.review_comment}"</p>
          )}
        </Card>
      )}

      {isPending && (
        <section className="flex flex-col gap-3">
          <div className="flex gap-2">
            <Button onClick={handleApprove} disabled={approveMut.isPending} className="flex-1">
              {approveMut.isPending ? 'Aprobando…' : 'Aprobar y abrir editor'}
            </Button>
            <Button
              variant="outline"
              onClick={() => setShowRejectForm((v) => !v)}
              disabled={rejectMut.isPending}
            >
              Rechazar
            </Button>
          </div>

          {approveMut.error && (
            <p className="text-xs text-danger-foreground">{approveMut.error.message}</p>
          )}

          {showRejectForm && (
            <Card className="bg-surface-muted p-4 space-y-3">
              <Textarea
                value={rejectComment}
                onChange={(e) => setRejectComment(e.target.value)}
                placeholder="Razón del rechazo (opcional)"
                rows={3}
              />
              <div className="flex gap-2 justify-end">
                <Button variant="ghost" size="sm" onClick={() => setShowRejectForm(false)}>
                  Cancelar
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleReject}
                  disabled={rejectMut.isPending}
                >
                  {rejectMut.isPending ? 'Rechazando…' : 'Confirmar rechazo'}
                </Button>
              </div>
              {rejectMut.error && (
                <p className="text-xs text-danger-foreground">{rejectMut.error.message}</p>
              )}
            </Card>
          )}
        </section>
      )}
    </div>
  )
}
