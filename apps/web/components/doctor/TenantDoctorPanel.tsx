'use client'

import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Copy,
  MinusCircle,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import { type DoctorCheck, type DoctorStatus, useTenantDoctor } from '@/lib/api/hooks/doctor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const GROUPS: Array<{ key: DoctorCheck['group']; label: string }> = [
  { key: 'platform', label: 'Plataforma' },
  { key: 'helpdesk', label: 'Helpdesk' },
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'commerce', label: 'Commerce' },
  { key: 'operations', label: 'Operación' },
]

const STATUS_META: Record<
  DoctorStatus,
  {
    label: string
    icon: typeof CheckCircle2
    className: string
    badge: 'success' | 'warning' | 'danger' | 'muted'
  }
> = {
  ok: { label: 'OK', icon: CheckCircle2, className: 'text-success-foreground', badge: 'success' },
  warn: {
    label: 'Aviso',
    icon: AlertTriangle,
    className: 'text-warning-foreground',
    badge: 'warning',
  },
  fail: { label: 'Fallo', icon: XCircle, className: 'text-danger-foreground', badge: 'danger' },
  skip: { label: 'Omitido', icon: MinusCircle, className: 'text-foreground-muted', badge: 'muted' },
}

const SUMMARY: Record<DoctorStatus, string> = {
  ok: 'Todo en orden',
  warn: 'Funciona, con avisos',
  fail: 'Hay fallos que arreglar',
  skip: 'Sin checks aplicables',
}

function looksLikeCommand(hint: string) {
  return hint.startsWith('python ') || hint.includes('scripts.')
}

function formatGeneratedAt(value: string) {
  return new Date(value).toLocaleString('es-ES', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function CommandHint({ hint }: { hint: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(hint)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch (err) {
      console.error('[auyan] no se pudo copiar el comando', err)
    }
  }
  return (
    <div className="mt-2 flex items-start gap-2 rounded-md bg-surface-muted px-3 py-2">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre font-mono text-xs text-foreground-body">
        {hint}
      </code>
      <button
        type="button"
        onClick={copy}
        className="shrink-0 text-foreground-muted hover:text-foreground"
        aria-label="Copiar comando"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  )
}

function CheckRow({ check }: { check: DoctorCheck }) {
  const meta = STATUS_META[check.status]
  const Icon = meta.icon
  return (
    <li className="flex gap-3 px-5 py-4">
      <Icon className={cn('mt-0.5 size-4 shrink-0', meta.className)} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-foreground">{check.title}</p>
          <span className="sr-only">{meta.label}</span>
        </div>
        <p className="mt-1 whitespace-pre-line text-sm text-foreground-muted">{check.detail}</p>
        {check.hint ? (
          looksLikeCommand(check.hint) ? (
            <CommandHint hint={check.hint} />
          ) : (
            <p className="mt-1.5 text-sm text-foreground-body">→ {check.hint}</p>
          )
        ) : null}
      </div>
    </li>
  )
}

export function TenantDoctorPanel({ tenantId }: { tenantId: string }) {
  const { data, isLoading, isFetching, isError, error, refetch } = useTenantDoctor(tenantId)
  const [onlyProblems, setOnlyProblems] = useState(false)

  const groups = useMemo(() => {
    if (!data) return []
    return GROUPS.map((group) => {
      const all = data.checks.filter((check) => check.group === group.key)
      const visible = onlyProblems
        ? all.filter((check) => check.status === 'warn' || check.status === 'fail')
        : all
      const problems = all.filter((c) => c.status === 'warn' || c.status === 'fail').length
      return { ...group, all, visible, problems }
    }).filter((group) => group.visible.length > 0)
  }, [data, onlyProblems])

  if (isLoading) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-foreground-muted">
          Comprobando migraciones, helpdesk, triggers y WhatsApp en vivo…
        </p>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        <span>{error instanceof Error ? error.message : 'No se pudo correr el doctor'}</span>
        <Button size="sm" variant="outline" onClick={() => refetch()}>
          Reintentar
        </Button>
      </div>
    )
  }

  const overall = STATUS_META[data.status]
  const OverallIcon = overall.icon
  const problems = (data.counts.warn ?? 0) + (data.counts.fail ?? 0)

  return (
    <div className="space-y-6">
      <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex items-center gap-3">
          <OverallIcon className={cn('size-6', overall.className)} aria-hidden />
          <div>
            <p className="text-base font-semibold text-foreground">{SUMMARY[data.status]}</p>
            <p className="text-xs text-foreground-muted">
              {data.tenant_slug} · {formatGeneratedAt(data.generated_at)} · {data.duration_ms} ms
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(['fail', 'warn', 'ok', 'skip'] as const).map((status) =>
            data.counts[status] ? (
              <Badge key={status} variant={STATUS_META[status].badge}>
                {data.counts[status]} {STATUS_META[status].label.toLowerCase()}
              </Badge>
            ) : null,
          )}
          <Button
            size="sm"
            variant="ghost"
            disabled={problems === 0}
            onClick={() => setOnlyProblems((value) => !value)}
          >
            {onlyProblems ? 'Ver todo' : 'Solo problemas'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn(isFetching && 'animate-spin')} />
            {isFetching ? 'Comprobando…' : 'Volver a correr'}
          </Button>
        </div>
      </Card>

      {groups.map((group) => (
        <section key={group.key} className="space-y-2">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
              {group.label}
            </h2>
            {group.problems > 0 ? (
              <span className="text-xs text-foreground-muted">
                · {group.problems} con problemas
              </span>
            ) : null}
          </div>
          <Card className="overflow-hidden">
            <ul className="divide-y divide-border">
              {group.visible.map((check) => (
                <CheckRow key={check.id} check={check} />
              ))}
            </ul>
          </Card>
        </section>
      ))}
    </div>
  )
}
