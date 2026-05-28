'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  type WeeklyReport,
  type WeeklyReportStatus,
  useApproveWeeklyReport,
  useGenerateWeeklyReport,
  useSendWeeklyReport,
  useSubmitWeeklyReport,
  useUpdateWeeklyReport,
  useWeeklyReports,
} from '@/lib/api/hooks/tenant-context'
import { cn } from '@/lib/utils'
import { CalendarPlus, Check, Clock3, FileBarChart2, Mail, Save, Send } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

const STATUS_LABELS: Record<WeeklyReportStatus, string> = {
  draft: 'Borrador',
  pending_review: 'En revisión',
  approved: 'Aprobado',
  sent: 'Enviado',
}

const STATUS_VARIANTS: Record<WeeklyReportStatus, 'muted' | 'warning' | 'success' | 'default'> = {
  draft: 'muted',
  pending_review: 'warning',
  approved: 'default',
  sent: 'success',
}

function metricNumber(report: WeeklyReport, path: string[], fallback = 0) {
  let value: unknown = report.metrics
  for (const key of path) {
    if (!value || typeof value !== 'object' || !(key in value)) return fallback
    value = (value as Record<string, unknown>)[key]
  }
  return typeof value === 'number' ? value : fallback
}

function previousWeekRange() {
  const end = new Date()
  end.setDate(end.getDate() - 1)
  const start = new Date(end)
  start.setDate(start.getDate() - 6)
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('es', { day: '2-digit', month: 'short' }).format(
    new Date(`${value}T00:00:00`),
  )
}

function StatusBadge({ status }: { status: WeeklyReportStatus }) {
  return <Badge variant={STATUS_VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>
}

export function WeeklyReportConsole({ tenantId }: { tenantId: string }) {
  const range = useMemo(previousWeekRange, [])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [weekStart, setWeekStart] = useState(range.start)
  const [weekEnd, setWeekEnd] = useState(range.end)
  const [recipientEmail, setRecipientEmail] = useState('')
  const [subject, setSubject] = useState('')
  const [narrative, setNarrative] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  const { data, isLoading, isError } = useWeeklyReports(tenantId)
  const generateMutation = useGenerateWeeklyReport(tenantId)
  const updateMutation = useUpdateWeeklyReport(tenantId)
  const submitMutation = useSubmitWeeklyReport(tenantId)
  const approveMutation = useApproveWeeklyReport(tenantId)
  const sendMutation = useSendWeeklyReport(tenantId)

  const active = useMemo(() => {
    if (!data?.length) return null
    return data.find((report) => report.id === activeId) ?? data[0]
  }, [activeId, data])

  useEffect(() => {
    if (!active) return
    setSubject(active.subject)
    setNarrative(active.narrative)
    setRecipientEmail(active.recipient_email ?? '')
    setMessage(null)
  }, [active])

  async function generate() {
    setMessage(null)
    try {
      const report = await generateMutation.mutateAsync({
        week_start: weekStart,
        week_end: weekEnd,
        recipient_email: recipientEmail.trim() || null,
      })
      setActiveId(report.id)
      setMessage('Borrador generado')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo generar')
    }
  }

  async function save() {
    if (!active) return
    setMessage(null)
    try {
      await updateMutation.mutateAsync({
        reportId: active.id,
        subject: subject.trim(),
        narrative: narrative.trim(),
        recipient_email: recipientEmail.trim() || null,
      })
      setMessage('Cambios guardados')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo guardar')
    }
  }

  async function transition(action: 'submit' | 'approve' | 'send') {
    if (!active) return
    setMessage(null)
    try {
      if (action === 'submit') await submitMutation.mutateAsync(active.id)
      if (action === 'approve') await approveMutation.mutateAsync(active.id)
      if (action === 'send') await sendMutation.mutateAsync(active.id)
      setMessage(
        action === 'submit'
          ? 'Enviado a revisión'
          : action === 'approve'
            ? 'Aprobado para envío'
            : 'Enviado por Postmark',
      )
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo actualizar')
    }
  }

  if (isLoading) return <Skeleton className="h-[680px]" />

  if (isError) {
    return (
      <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudieron cargar los reportes.
      </div>
    )
  }

  const busy =
    generateMutation.isPending ||
    updateMutation.isPending ||
    submitMutation.isPending ||
    approveMutation.isPending ||
    sendMutation.isPending

  return (
    <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
      <div className="space-y-4">
        <Card className="p-(--density-card-p)">
          <div className="flex items-center gap-2">
            <CalendarPlus className="size-4 text-accent-foreground" />
            <p className="text-sm font-semibold text-foreground">Nuevo reporte</p>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Input type="date" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} />
            <Input type="date" value={weekEnd} onChange={(e) => setWeekEnd(e.target.value)} />
          </div>
          <Input
            className="mt-3"
            type="email"
            value={recipientEmail}
            onChange={(e) => setRecipientEmail(e.target.value)}
            placeholder="ops@cliente.com"
          />
          <Button className="mt-3 w-full" onClick={() => void generate()} disabled={busy}>
            <CalendarPlus className="size-4" />
            Generar borrador
          </Button>
        </Card>

        <Card className="overflow-hidden p-2">
          <div className="border-b border-border-subtle px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <FileBarChart2 className="size-4 text-accent-foreground" />
                <p className="text-sm font-semibold text-foreground">Reportes</p>
              </div>
              <Badge variant={(data?.length ?? 0) > 0 ? 'default' : 'secondary'}>
                {data?.length ?? 0}
              </Badge>
            </div>
          </div>
          <nav className="max-h-[440px] space-y-1 overflow-y-auto p-2">
            {(data ?? []).map((report) => {
              const isActive = active?.id === report.id
              return (
                <button
                  key={report.id}
                  type="button"
                  onClick={() => setActiveId(report.id)}
                  className={cn(
                    'w-full rounded-sm px-3 py-2 text-left transition-colors',
                    isActive ? 'bg-accent-subtle text-accent-foreground' : 'hover:bg-surface-muted',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium">
                      {formatDate(report.week_start)} - {formatDate(report.week_end)}
                    </p>
                    <StatusBadge status={report.status} />
                  </div>
                  <p className="mt-1 truncate text-xs text-foreground-muted">
                    {report.recipient_email ?? 'Sin destinatario'}
                  </p>
                </button>
              )
            })}
            {data?.length === 0 && (
              <p className="px-3 py-4 text-sm text-foreground-muted">Sin reportes aún.</p>
            )}
          </nav>
        </Card>
      </div>

      <Card className="min-h-[680px] p-(--density-card-p)">
        {active ? (
          <div className="space-y-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold text-foreground">Reporte semanal</h2>
                  <StatusBadge status={active.status} />
                </div>
                <p className="mt-1 text-sm text-foreground-muted">
                  {active.week_start} a {active.week_end}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={() => void save()}
                  disabled={busy || active.status !== 'draft'}
                >
                  <Save className="size-4" />
                  Guardar
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => void transition('submit')}
                  disabled={busy || active.status !== 'draft'}
                >
                  <Clock3 className="size-4" />
                  Revisar
                </Button>
                <Button
                  onClick={() => void transition('approve')}
                  disabled={busy || active.status !== 'pending_review'}
                >
                  <Check className="size-4" />
                  Aprobar
                </Button>
                <Button
                  onClick={() => void transition('send')}
                  disabled={busy || active.status !== 'approved'}
                >
                  <Send className="size-4" />
                  Enviar
                </Button>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-4">
              <Metric
                label="Conversaciones"
                value={metricNumber(active, ['volume', 'conversations'])}
              />
              <Metric label="Mensajes" value={metricNumber(active, ['volume', 'messages'])} />
              <Metric
                label="Resolución"
                value={`${metricNumber(active, ['resolution_rate']).toFixed(1)}%`}
              />
              <Metric
                label="Coste"
                value={`$${metricNumber(active, ['cost', 'usd']).toFixed(4)}`}
              />
            </div>

            <div className="grid gap-3 md:grid-cols-[1fr_220px]">
              <Input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                disabled={active.status !== 'draft'}
              />
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-2.5 size-4 text-foreground-muted" />
                <Input
                  className="pl-9"
                  type="email"
                  value={recipientEmail}
                  onChange={(e) => setRecipientEmail(e.target.value)}
                  disabled={active.status !== 'draft'}
                />
              </div>
            </div>

            <Textarea
              value={narrative}
              onChange={(e) => setNarrative(e.target.value)}
              disabled={active.status !== 'draft'}
              className="min-h-[300px]"
            />

            {active.send_error && (
              <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
                {active.send_error}
              </div>
            )}
            {message && <p className="text-sm text-foreground-muted">{message}</p>}
          </div>
        ) : (
          <div className="flex min-h-[560px] items-center justify-center text-sm text-foreground-muted">
            Selecciona o genera un reporte.
          </div>
        )}
      </Card>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border-subtle bg-surface-muted px-3 py-3">
      <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">{label}</p>
      <p className="mt-2 text-xl font-semibold tabular-nums text-foreground">{value}</p>
    </div>
  )
}
