'use client'

import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { useApprovals, useApproveMutation, useRejectMutation } from '@/lib/api/hooks/approvals'
import type { ApprovalOut, ApprovalStatus } from '@/lib/api/hooks/approvals'
import Link from 'next/link'
import { useState } from 'react'

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

const STATUS_VARIANT: Record<ApprovalStatus, BadgeProps['variant']> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
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

const SKILL_LABELS: Record<string, string> = {
  'shopify.update_shipping_address': 'Cambiar dirección de envío',
  'shopify.cancel_order': 'Cancelar pedido',
  'shopify.refund_partial': 'Reembolso parcial',
  'shopify.start_return': 'Iniciar devolución',
  'shopify.add_order_note': 'Añadir nota al pedido',
  'shopify.tag_order': 'Etiquetar pedido',
  'shopify.get_order_status': 'Consultar estado del pedido',
  'shopify.list_my_orders': 'Listar pedidos del cliente',
  'shopify.get_shop_policies': 'Consultar políticas de la tienda',
  'shopify.get_product_info': 'Consultar producto',
}

const AOP_LABELS: Record<string, string> = {
  order_status: 'Estado de pedido',
  shipping_info: 'Información de envío',
  order_change: 'Cambio de pedido',
  returns: 'Devoluciones',
  refunds: 'Reembolsos',
  product_info: 'Información de producto',
  complaint: 'Reclamación',
  smalltalk: 'Conversación general',
  default: 'General',
}

const INPUT_LABELS: Record<string, string> = {
  order_id: 'Pedido',
  reason: 'Motivo',
  address1: 'Dirección',
  address2: 'Dirección (línea 2)',
  city: 'Ciudad',
  province: 'Provincia',
  zip_code: 'Código postal',
  country: 'País',
  country_code: 'País',
  send_email: 'Notificar por email',
  refund_payment: 'Reembolsar pago',
  restock: 'Reponer stock',
  amount: 'Importe',
  currency: 'Moneda',
  note: 'Nota',
  tag: 'Etiqueta',
  email: 'Email',
  phone: 'Teléfono',
  first_name: 'Nombre',
  last_name: 'Apellidos',
}

const CANCEL_REASON_LABELS: Record<string, string> = {
  customer: 'solicitado por el cliente',
  fraud: 'fraude',
  inventory: 'sin stock',
  declined: 'pago rechazado',
  other: 'otro',
}

function humanizeSlug(slug: string): string {
  const base = slug.includes('.') ? slug.split('.').pop()! : slug
  return base.replaceAll('_', ' ')
}

function skillLabel(slug: string): string {
  return SKILL_LABELS[slug] ?? humanizeSlug(slug)
}

function aopLabel(slug: string): string {
  return AOP_LABELS[slug] ?? humanizeSlug(slug)
}

function formatInputValue(key: string, value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Sí' : 'No'
  if (key === 'reason' && typeof value === 'string') {
    return CANCEL_REASON_LABELS[value] ?? value
  }
  return String(value)
}

function formatInputs(inputs: Record<string, unknown>): string {
  return Object.entries(inputs)
    .map(([k, v]) => `${INPUT_LABELS[k] ?? k.replaceAll('_', ' ')}: ${formatInputValue(k, v)}`)
    .join(' · ')
}

// ----------------------------------------------------------------
// Reject dialog
// ----------------------------------------------------------------

function RejectDialog({
  open,
  onOpenChange,
  onConfirm,
  isPending,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onConfirm: (comment: string) => void
  isPending: boolean
}) {
  const [comment, setComment] = useState('')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rechazar acción</DialogTitle>
          <DialogDescription>Indica el motivo del rechazo.</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="reject-reason">Motivo</Label>
          <Textarea
            id="reject-reason"
            autoFocus
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Motivo del rechazo…"
            rows={3}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancelar
          </Button>
          <Button
            variant="destructive"
            onClick={() => comment.trim() && onConfirm(comment.trim())}
            disabled={isPending || !comment.trim()}
          >
            {isPending ? 'Rechazando…' : 'Rechazar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ----------------------------------------------------------------
// Row
// ----------------------------------------------------------------

function ApprovalRow({
  approval,
  conversationBasePath,
  onApprove,
  onReject,
  isActing,
}: {
  approval: ApprovalOut
  conversationBasePath: string
  onApprove: (id: string) => void
  onReject: (id: string) => void
  isActing: boolean
}) {
  const isPending = approval.status === 'pending'
  return (
    <div className="px-4 py-3 hover:bg-surface-muted transition-colors">
      <div className="flex items-start gap-3">
        <Badge variant={STATUS_VARIANT[approval.status]} className="mt-0.5">
          {STATUS_LABELS[approval.status]}
        </Badge>

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground-body">{skillLabel(approval.skill_slug)}</p>
          <p className="mt-0.5 text-xs text-foreground-muted truncate">
            {formatInputs(approval.inputs_raw)}
          </p>
          <div className="mt-1 flex items-center gap-2 text-xs text-foreground-muted">
            <Link
              href={`${conversationBasePath}/${approval.conversation_id}`}
              className="text-accent-foreground hover:underline underline-offset-2"
            >
              Ver conversación
            </Link>
            <span>·</span>
            <span>
              Procedimiento: {aopLabel(approval.aop_slug)} (v{approval.aop_version})
            </span>
            <span>·</span>
            <span className="tabular-nums">{relativeTime(approval.created_at)}</span>
          </div>
          {approval.review_comment && (
            <p className="mt-1 text-xs text-foreground-muted italic">
              &ldquo;{approval.review_comment}&rdquo;
            </p>
          )}
        </div>

        {isPending && (
          <div className="shrink-0 flex gap-2">
            <Button size="sm" onClick={() => onApprove(approval.id)} disabled={isActing}>
              Aprobar
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onReject(approval.id)}
              disabled={isActing}
              className="border-danger-subtle text-danger-foreground hover:bg-danger-subtle"
            >
              Rechazar
            </Button>
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

export function ApprovalQueue({
  tenantId,
  conversationBasePath = `/tenants/${tenantId}/conversations`,
}: {
  tenantId: string
  conversationBasePath?: string
}) {
  const [activeStatus, setActiveStatus] = useState<ApprovalStatus | 'all'>('pending')
  const [offset, setOffset] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)

  const status = activeStatus === 'all' ? undefined : activeStatus

  const {
    data,
    isLoading,
    isError,
    error: queryError,
  } = useApprovals({
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
      const result = await approveMutation.mutateAsync({ approvalId: id })
      // La ejecución de la skill puede fallar aunque el endpoint responda 200:
      // la aprobación sigue pendiente para reintentar y no se le confirma nada
      // al cliente. Mostramos el fallo en vez de tratarlo como éxito silencioso.
      if (result.execution_status === 'failed') {
        const detail =
          typeof result.output?.error === 'string' ? result.output.error : 'error desconocido'
        setActionError(`No se pudo ejecutar la acción: ${detail}. Sigue pendiente, reintenta.`)
      }
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
      <RejectDialog
        open={!!rejectingId}
        onOpenChange={(v) => !v && setRejectingId(null)}
        onConfirm={handleRejectConfirm}
        isPending={rejectMutation.isPending}
      />

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-foreground">Aprobaciones</h1>
          {isLoading && <span className="text-xs text-foreground-muted">Actualizando…</span>}
        </div>

        <Tabs
          value={activeStatus}
          onValueChange={(v) => {
            setActiveStatus(v as ApprovalStatus | 'all')
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

        {actionError && (
          <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
            {actionError}
          </div>
        )}

        {isError ? (
          <div className="rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
            Error al cargar: {queryError instanceof Error ? queryError.message : 'desconocido'}
          </div>
        ) : approvals.length === 0 && !isLoading ? (
          <div className="py-12 text-center text-sm text-foreground-muted">
            No hay aprobaciones{' '}
            {activeStatus !== 'all' && `con estado "${FILTER_LABELS[activeStatus]}"`}.
          </div>
        ) : (
          <div className="divide-y divide-border-subtle rounded-md border border-border bg-surface">
            {approvals.map((a) => (
              <ApprovalRow
                key={a.id}
                approval={a}
                conversationBasePath={conversationBasePath}
                onApprove={handleApprove}
                onReject={setRejectingId}
                isActing={isActing}
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
    </>
  )
}
