'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  ACTIVE_INGESTION_STATUSES,
  type IngestionStatus,
  type IngestionSubmission,
  type SiteIngestion,
  type SourceStats,
  useApproveIngestionBatch,
  useIngestionSubmissions,
  useLatestSiteIngestion,
  useStartSiteIngestion,
} from '@/lib/api/hooks/site-ingestions'
import { Check, Globe, Loader2 } from 'lucide-react'
import { useState } from 'react'

const STATUS_LABEL: Record<IngestionStatus, string> = {
  queued: 'En cola',
  fetching: 'Leyendo el sitio',
  extracting: 'Guardando fuentes',
  ready: 'Lista',
  failed: 'Falló',
}

const STATUS_VARIANT: Record<IngestionStatus, 'secondary' | 'warning' | 'success' | 'danger'> = {
  queued: 'secondary',
  fetching: 'warning',
  extracting: 'warning',
  ready: 'success',
  failed: 'danger',
}

const SOURCE_LABEL: Record<string, string> = {
  storefront_api: 'API pública de la tienda',
  agent_files: 'Archivos para agentes',
  html: 'Páginas HTML',
}

const SUBMISSION_STATUS_LABEL: Record<IngestionSubmission['status'], string> = {
  pending_review: 'Pendiente',
  approved: 'Aprobada',
  rejected: 'Rechazada',
  superseded: 'Sustituida',
}

function discardedSummary(discarded: Record<string, number>) {
  const parts = Object.entries(discarded).map(([reason, count]) => `${reason} ${count}`)
  return parts.length ? parts.join(', ') : 'nada'
}

function SourceRow({ name, stats }: { name: string; stats: SourceStats }) {
  return (
    <tr className="border-t border-border-subtle align-top">
      <td className="py-2 pr-3 font-medium text-foreground">{SOURCE_LABEL[name] ?? name}</td>
      <td className="py-2 pr-3 tabular-nums">{stats.docs}</td>
      <td className="py-2 pr-3 tabular-nums">{stats.words}</td>
      <td className="py-2 pr-3 tabular-nums">{stats.requests}</td>
      <td className="py-2 pr-3 tabular-nums">{stats.rate_limited}</td>
      <td className="py-2 text-foreground-muted">
        {stats.abandoned && (
          <p className="text-warning-foreground">Abandonada: {stats.abandoned}</p>
        )}
        <p>Descartadas: {discardedSummary(stats.discarded)}</p>
      </td>
    </tr>
  )
}

function IngestionStatsTable({ ingestion }: { ingestion: SiteIngestion }) {
  const sources = Object.entries(ingestion.stats.sources ?? {})
  if (sources.length === 0) return null
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="text-xs uppercase tracking-wider text-foreground-muted">
          <tr>
            <th className="pb-2 pr-3 font-medium">Fuente</th>
            <th className="pb-2 pr-3 font-medium">Docs</th>
            <th className="pb-2 pr-3 font-medium">Palabras</th>
            <th className="pb-2 pr-3 font-medium">Peticiones</th>
            <th className="pb-2 pr-3 font-medium">429</th>
            <th className="pb-2 font-medium">Notas</th>
          </tr>
        </thead>
        <tbody className="text-foreground-body">
          {sources.map(([name, stats]) => (
            <SourceRow key={name} name={name} stats={stats} />
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-foreground-muted">
        robots.txt: {ingestion.stats.robots ?? 'desconocido'} · {ingestion.stats.requests ?? 0}{' '}
        peticiones en {ingestion.stats.seconds ?? 0} s
      </p>
    </div>
  )
}

function BatchReview({ tenantId, ingestion }: { tenantId: string; ingestion: SiteIngestion }) {
  const { data, isLoading, isError } = useIngestionSubmissions(tenantId, ingestion.id)
  const approve = useApproveIngestionBatch(tenantId, ingestion.id)
  const [overrides, setOverrides] = useState<Record<string, boolean>>({})
  const [message, setMessage] = useState<string | null>(null)

  if (isLoading) return <Skeleton className="mt-4 h-32" />
  if (isError || !data) {
    return <p className="mt-4 text-sm text-danger-foreground">No se pudieron cargar las fuentes.</p>
  }

  const pending = data.filter((item) => item.status === 'pending_review')
  const isChecked = (item: IngestionSubmission) => overrides[item.id] ?? item.priority !== 'low'
  const keep = pending.filter(isChecked)
  const excluded = pending.filter((item) => !isChecked(item))

  async function submit() {
    setMessage(null)
    try {
      const result = await approve.mutateAsync({
        excludeSubmissionIds: excluded.map((item) => item.id),
      })
      setOverrides({})
      const { approved, rejected, skipped } = result.counts
      const failed = result.failures.length
      const failures = failed ? `, ${failed} con error (siguen pendientes)` : ''
      setMessage(
        `Aprobadas ${approved}, rechazadas ${rejected}, ya revisadas ${skipped}${failures}`,
      )
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo aprobar el lote')
    }
  }

  return (
    <div className="mt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">
          Fuentes leídas <Badge variant="secondary">{data.length}</Badge>
        </h3>
        {pending.length > 0 && (
          <Button onClick={() => void submit()} disabled={approve.isPending || keep.length === 0}>
            <Check className="size-4" />
            {approve.isPending ? 'Indexando lote' : `Aprobar lote (${keep.length})`}
          </Button>
        )}
      </div>
      {pending.length > 0 && (
        <p className="mt-1 text-xs text-foreground-muted">
          Las fuentes sin marcar se rechazan. Las de prioridad baja vienen sin marcar.
        </p>
      )}
      <ul className="mt-3 divide-y divide-border-subtle">
        {data.map((item) => {
          const isPending = item.status === 'pending_review'
          return (
            <li key={item.id} className="flex items-start gap-3 py-2">
              <input
                type="checkbox"
                aria-label={`Incluir ${item.title}`}
                className="mt-1 size-4 accent-[var(--color-accent)]"
                checked={isPending ? isChecked(item) : item.status === 'approved'}
                disabled={!isPending}
                onChange={(event) =>
                  setOverrides((prev) => ({ ...prev, [item.id]: event.target.checked }))
                }
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">{item.title}</p>
                <p className="truncate text-xs text-foreground-muted">
                  {item.source_key ?? item.source_url} · {item.kind ?? 'sin tipo'} ·{' '}
                  {item.words ?? 0} palabras
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {item.priority === 'low' && <Badge variant="muted">Prioridad baja</Badge>}
                <Badge variant={isPending ? 'warning' : 'secondary'}>
                  {SUBMISSION_STATUS_LABEL[item.status]}
                </Badge>
              </div>
            </li>
          )
        })}
      </ul>
      {message && <p className="mt-3 text-sm text-foreground-muted">{message}</p>}
    </div>
  )
}

export function SiteIngestions({ tenantId }: { tenantId: string }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const { data: ingestion, isLoading } = useLatestSiteIngestion(tenantId)
  const start = useStartSiteIngestion(tenantId)
  const active = ingestion ? ACTIVE_INGESTION_STATUSES.includes(ingestion.status) : false

  async function launch() {
    setError(null)
    try {
      await start.mutateAsync(url.trim())
      setUrl('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo lanzar la ingesta')
    }
  }

  return (
    <Card className="p-(--density-card-p)">
      <div className="flex items-center gap-2">
        <Globe className="size-4 text-accent-foreground" />
        <h2 className="text-sm font-semibold text-foreground">Ingestas</h2>
      </div>
      <p className="mt-1 text-sm text-foreground-muted">
        Lee la web de la tienda con el bot identificado y deja sus fuentes pendientes de revisión.
      </p>

      <form
        className="mt-3 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void launch()
        }}
      >
        <Input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://tienda.com"
          aria-label="URL de la tienda"
          className="max-w-sm"
          disabled={active}
        />
        <Button type="submit" disabled={start.isPending || active || url.trim() === ''}>
          {start.isPending ? 'Lanzando' : 'Ingestar'}
        </Button>
      </form>
      {error && <p className="mt-2 text-sm text-danger-foreground">{error}</p>}

      {isLoading && <Skeleton className="mt-4 h-16" />}
      {ingestion && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={STATUS_VARIANT[ingestion.status]}>
              {active && <Loader2 className="mr-1 size-3 animate-spin" />}
              {STATUS_LABEL[ingestion.status]}
            </Badge>
            <span className="text-sm text-foreground-body">{ingestion.root_url}</span>
            {ingestion.platform && <Badge variant="outline">{ingestion.platform}</Badge>}
          </div>
          {ingestion.failure_reason && (
            <p className="mt-2 text-sm text-danger-foreground">{ingestion.failure_reason}</p>
          )}
          <IngestionStatsTable ingestion={ingestion} />
          {ingestion.status === 'ready' && (
            <BatchReview tenantId={tenantId} ingestion={ingestion} />
          )}
        </div>
      )}
    </Card>
  )
}
