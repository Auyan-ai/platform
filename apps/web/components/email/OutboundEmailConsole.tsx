'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  type OutboundEmailJob,
  type OutboundEmailJobStatus,
  type OutboundEmailTemplate,
  useCreateOutboundEmailTemplate,
  useEnqueueOutboundEmailJob,
  useOutboundEmailJobs,
  useOutboundEmailTemplates,
  useUpdateOutboundEmailTemplate,
} from '@/lib/api/hooks/tenant-context'
import { cn } from '@/lib/utils'
import { Clock3, MailPlus, Save, Send, SquarePen } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

const STATUS_LABELS: Record<OutboundEmailJobStatus, string> = {
  queued: 'Queued',
  sending: 'Sending',
  sent: 'Sent',
  failed: 'Failed',
  canceled: 'Canceled',
}

const STATUS_VARIANTS: Record<
  OutboundEmailJobStatus,
  'muted' | 'warning' | 'success' | 'danger' | 'default'
> = {
  queued: 'muted',
  sending: 'warning',
  sent: 'success',
  failed: 'danger',
  canceled: 'default',
}

function variablesFromText(value: string) {
  return Array.from(value.matchAll(/\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}/g))
    .map((match) => match[1])
    .filter((item, index, arr) => arr.indexOf(item) === index)
}

function formatDateTime(value: string | null) {
  if (!value) return '...'
  return new Intl.DateTimeFormat('es', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function templateDraft(template?: OutboundEmailTemplate | null) {
  return {
    key: template?.key ?? '',
    name: template?.name ?? '',
    subject_template: template?.subject_template ?? '',
    text_body_template: template?.text_body_template ?? '',
    html_body_template: template?.html_body_template ?? '',
    variables: template?.variables.join(', ') ?? '',
    is_active: template?.is_active ?? true,
  }
}

function jobDraft(template?: OutboundEmailTemplate | null) {
  return {
    template_id: template?.id ?? '',
    recipient_email: '',
    subject: template?.subject_template ?? '',
    text_body: template?.text_body_template ?? '',
    html_body: template?.html_body_template ?? '',
    tag: template?.key ?? '',
    idempotency_key: '',
    payload: '{}',
    max_attempts: 3,
  }
}

export function OutboundEmailConsole({ tenantId }: { tenantId: string }) {
  const [activeTemplateId, setActiveTemplateId] = useState<string | null>(null)
  const [templateForm, setTemplateForm] = useState(templateDraft())
  const [jobForm, setJobForm] = useState(jobDraft())
  const [message, setMessage] = useState<string | null>(null)

  const templates = useOutboundEmailTemplates(tenantId)
  const jobs = useOutboundEmailJobs(tenantId)
  const createTemplate = useCreateOutboundEmailTemplate(tenantId)
  const updateTemplate = useUpdateOutboundEmailTemplate(tenantId)
  const enqueueJob = useEnqueueOutboundEmailJob(tenantId)

  const activeTemplate = useMemo(() => {
    if (!templates.data?.length || activeTemplateId === 'new') return null
    return templates.data.find((template) => template.id === activeTemplateId) ?? templates.data[0]
  }, [activeTemplateId, templates.data])

  useEffect(() => {
    if (!templates.data?.length || activeTemplateId) return
    setActiveTemplateId(templates.data[0].id)
  }, [activeTemplateId, templates.data])

  useEffect(() => {
    setTemplateForm(templateDraft(activeTemplate))
  }, [activeTemplate])

  function startNewTemplate() {
    setActiveTemplateId('new')
    setTemplateForm(templateDraft())
    setMessage(null)
  }

  function syncVariables() {
    const variables = [
      ...variablesFromText(templateForm.subject_template),
      ...variablesFromText(templateForm.text_body_template),
      ...variablesFromText(templateForm.html_body_template),
    ].filter((item, index, arr) => arr.indexOf(item) === index)
    setTemplateForm((prev) => ({ ...prev, variables: variables.join(', ') }))
  }

  async function saveTemplate() {
    setMessage(null)
    const variables = templateForm.variables
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    try {
      if (activeTemplate) {
        await updateTemplate.mutateAsync({
          templateId: activeTemplate.id,
          name: templateForm.name.trim(),
          subject_template: templateForm.subject_template.trim(),
          text_body_template: templateForm.text_body_template.trim(),
          html_body_template: templateForm.html_body_template.trim() || null,
          variables,
          is_active: templateForm.is_active,
        })
        setMessage('Template actualizado')
      } else {
        const created = await createTemplate.mutateAsync({
          key: templateForm.key.trim(),
          name: templateForm.name.trim(),
          subject_template: templateForm.subject_template.trim(),
          text_body_template: templateForm.text_body_template.trim(),
          html_body_template: templateForm.html_body_template.trim() || null,
          variables,
          is_active: templateForm.is_active,
        })
        setActiveTemplateId(created.id)
        setMessage('Template creado')
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo guardar')
    }
  }

  function useTemplateForJob(template: OutboundEmailTemplate) {
    setJobForm(jobDraft(template))
    setMessage(null)
  }

  async function enqueue() {
    setMessage(null)
    try {
      const payload = JSON.parse(jobForm.payload || '{}') as Record<string, unknown>
      await enqueueJob.mutateAsync({
        template_id: jobForm.template_id || null,
        recipient_email: jobForm.recipient_email.trim(),
        subject: jobForm.subject.trim(),
        text_body: jobForm.text_body.trim(),
        html_body: jobForm.html_body.trim() || null,
        tag: jobForm.tag.trim() || null,
        idempotency_key: jobForm.idempotency_key.trim() || null,
        payload,
        max_attempts: jobForm.max_attempts,
      })
      setMessage('Email encolado')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'No se pudo encolar')
    }
  }

  if (templates.isLoading || jobs.isLoading) return <Skeleton className="h-[720px]" />

  if (templates.isError || jobs.isError) {
    return (
      <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudo cargar la consola de emails.
      </div>
    )
  }

  const busy = createTemplate.isPending || updateTemplate.isPending || enqueueJob.isPending

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="space-y-4">
        <Card className="overflow-hidden p-2">
          <div className="flex items-center justify-between border-b border-border-subtle px-3 py-3">
            <div className="flex items-center gap-2">
              <SquarePen className="size-4 text-accent-foreground" />
              <p className="text-sm font-semibold text-foreground">Templates</p>
            </div>
            <Button size="sm" variant="secondary" onClick={startNewTemplate}>
              Nuevo
            </Button>
          </div>
          <nav className="max-h-[420px] space-y-1 overflow-y-auto p-2">
            {(templates.data ?? []).map((template) => (
              <button
                key={template.id}
                type="button"
                onClick={() => setActiveTemplateId(template.id)}
                className={cn(
                  'w-full rounded-sm px-3 py-2 text-left transition-colors',
                  activeTemplate?.id === template.id
                    ? 'bg-accent-subtle text-accent-foreground'
                    : 'hover:bg-surface-muted',
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-sm font-medium">{template.name}</p>
                  <Badge variant={template.is_active ? 'success' : 'muted'}>
                    v{template.version}
                  </Badge>
                </div>
                <p className="mt-1 truncate text-xs text-foreground-muted">{template.key}</p>
              </button>
            ))}
            {templates.data?.length === 0 && (
              <p className="px-3 py-4 text-sm text-foreground-muted">Sin templates.</p>
            )}
          </nav>
        </Card>

        <Card className="p-(--density-card-p)">
          <div className="flex items-center gap-2">
            <MailPlus className="size-4 text-accent-foreground" />
            <p className="text-sm font-semibold text-foreground">Encolar email</p>
          </div>
          <select
            className="mt-4 h-9 w-full rounded-sm border border-border bg-surface px-3 text-sm"
            value={jobForm.template_id}
            onChange={(event) => {
              const template = templates.data?.find((item) => item.id === event.target.value)
              setJobForm(jobDraft(template ?? null))
            }}
          >
            <option value="">Sin template</option>
            {(templates.data ?? []).map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}
              </option>
            ))}
          </select>
          <Input
            className="mt-3"
            type="email"
            placeholder="ops@cliente.com"
            value={jobForm.recipient_email}
            onChange={(event) =>
              setJobForm((prev) => ({ ...prev, recipient_email: event.target.value }))
            }
          />
          <Input
            className="mt-3"
            placeholder="Tag"
            value={jobForm.tag}
            onChange={(event) => setJobForm((prev) => ({ ...prev, tag: event.target.value }))}
          />
          <Input
            className="mt-3"
            placeholder="Subject"
            value={jobForm.subject}
            onChange={(event) => setJobForm((prev) => ({ ...prev, subject: event.target.value }))}
          />
          <Textarea
            className="mt-3 min-h-[110px]"
            placeholder="Text body"
            value={jobForm.text_body}
            onChange={(event) => setJobForm((prev) => ({ ...prev, text_body: event.target.value }))}
          />
          <Textarea
            className="mt-3 min-h-[90px]"
            placeholder="HTML body opcional"
            value={jobForm.html_body}
            onChange={(event) => setJobForm((prev) => ({ ...prev, html_body: event.target.value }))}
          />
          <Textarea
            className="mt-3 min-h-[80px] font-mono text-xs"
            placeholder="Payload JSON"
            value={jobForm.payload}
            onChange={(event) => setJobForm((prev) => ({ ...prev, payload: event.target.value }))}
          />
          <div className="mt-3 grid gap-3 md:grid-cols-[1fr_96px]">
            <Input
              placeholder="idempotency key"
              value={jobForm.idempotency_key}
              onChange={(event) =>
                setJobForm((prev) => ({ ...prev, idempotency_key: event.target.value }))
              }
            />
            <Input
              type="number"
              min={1}
              max={10}
              value={jobForm.max_attempts}
              onChange={(event) =>
                setJobForm((prev) => ({
                  ...prev,
                  max_attempts: Number(event.target.value),
                }))
              }
            />
          </div>
          <Button className="mt-3 w-full" onClick={() => void enqueue()} disabled={busy}>
            <Send className="size-4" />
            Encolar
          </Button>
        </Card>
      </div>

      <div className="space-y-4">
        <Card className="p-(--density-card-p)">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                {activeTemplate ? 'Editar template' : 'Nuevo template'}
              </h2>
              <p className="mt-1 text-sm text-foreground-muted">
                Variables con sintaxis {'{{variable}}'} quedan registradas para revisión.
              </p>
            </div>
            <div className="flex gap-2">
              {activeTemplate && (
                <Button
                  variant="secondary"
                  onClick={() => useTemplateForJob(activeTemplate)}
                  disabled={busy}
                >
                  <MailPlus className="size-4" />
                  Usar
                </Button>
              )}
              <Button onClick={() => void saveTemplate()} disabled={busy}>
                <Save className="size-4" />
                Guardar
              </Button>
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-[180px_1fr]">
            <Input
              placeholder="key"
              value={templateForm.key}
              disabled={Boolean(activeTemplate)}
              onChange={(event) =>
                setTemplateForm((prev) => ({ ...prev, key: event.target.value }))
              }
            />
            <Input
              placeholder="Nombre"
              value={templateForm.name}
              onChange={(event) =>
                setTemplateForm((prev) => ({ ...prev, name: event.target.value }))
              }
            />
          </div>
          <Input
            className="mt-3"
            placeholder="Subject"
            value={templateForm.subject_template}
            onChange={(event) =>
              setTemplateForm((prev) => ({ ...prev, subject_template: event.target.value }))
            }
          />
          <Textarea
            className="mt-3 min-h-[180px]"
            placeholder="Text body"
            value={templateForm.text_body_template}
            onChange={(event) =>
              setTemplateForm((prev) => ({ ...prev, text_body_template: event.target.value }))
            }
          />
          <Textarea
            className="mt-3 min-h-[120px]"
            placeholder="HTML body opcional"
            value={templateForm.html_body_template}
            onChange={(event) =>
              setTemplateForm((prev) => ({ ...prev, html_body_template: event.target.value }))
            }
          />
          <div className="mt-3 grid gap-3 md:grid-cols-[1fr_140px]">
            <Input
              placeholder="variables separadas por coma"
              value={templateForm.variables}
              onChange={(event) =>
                setTemplateForm((prev) => ({ ...prev, variables: event.target.value }))
              }
            />
            <Button variant="secondary" onClick={syncVariables}>
              Detectar
            </Button>
          </div>
        </Card>

        <Card className="p-(--density-card-p)">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Clock3 className="size-4 text-accent-foreground" />
              <p className="text-sm font-semibold text-foreground">Cola reciente</p>
            </div>
            <Badge variant={(jobs.data?.length ?? 0) > 0 ? 'default' : 'secondary'}>
              {jobs.data?.length ?? 0}
            </Badge>
          </div>
          <div className="mt-4 overflow-hidden rounded-md border border-border-subtle">
            {(jobs.data ?? []).slice(0, 12).map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
            {jobs.data?.length === 0 && (
              <p className="px-4 py-6 text-sm text-foreground-muted">Sin jobs todavía.</p>
            )}
          </div>
          {message && <p className="mt-3 text-sm text-foreground-muted">{message}</p>}
        </Card>
      </div>
    </div>
  )
}

function JobRow({ job }: { job: OutboundEmailJob }) {
  return (
    <div className="grid gap-2 border-b border-border-subtle px-4 py-3 last:border-b-0 md:grid-cols-[1fr_130px_90px]">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{job.subject}</p>
        <p className="mt-1 truncate text-xs text-foreground-muted">{job.recipient_email}</p>
        {job.error && <p className="mt-1 truncate text-xs text-danger-foreground">{job.error}</p>}
      </div>
      <p className="text-xs text-foreground-muted">{formatDateTime(job.created_at)}</p>
      <div className="flex items-start justify-end">
        <Badge variant={STATUS_VARIANTS[job.status]}>{STATUS_LABELS[job.status]}</Badge>
      </div>
    </div>
  )
}
