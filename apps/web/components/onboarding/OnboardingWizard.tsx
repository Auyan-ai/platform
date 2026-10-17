'use client'

import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, Send, Save } from 'lucide-react'
import {
  useSaveTenantOnboarding,
  useSubmitTenantOnboarding,
  useTenantOnboarding,
  useTenantOnboardingChecklist,
} from '@/lib/api/hooks/tenant-context'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { HelpdeskConnectStep } from './HelpdeskConnectStep'
import { KbUploadStep } from './KbUploadStep'
import { OnboardingChecklistBanner } from './OnboardingChecklistBanner'
import { ShopifyConnectStep } from './ShopifyConnectStep'

type Field = {
  key: string
  label: string
  placeholder?: string
  kind?: 'input' | 'textarea' | 'checkbox'
}

const STEPS: Array<{ id: number; title: string; fields: Field[] }> = [
  {
    id: 1,
    title: 'Datos básicos',
    fields: [
      { key: 'company_name', label: 'Nombre comercial', placeholder: 'Lunaria' },
      { key: 'website_url', label: 'Web', placeholder: 'https://tienda.com' },
      { key: 'primary_contact', label: 'Contacto principal', placeholder: 'Nombre y cargo' },
      { key: 'support_volume', label: 'Tickets mensuales', placeholder: '1.000-3.000' },
    ],
  },
  {
    id: 2,
    title: 'Voz de marca',
    fields: [
      {
        key: 'voice_traits',
        label: 'Tono deseado',
        placeholder: 'Cercano, claro, resolutivo, sin sonar robótico',
        kind: 'textarea',
      },
      {
        key: 'forbidden_phrases',
        label: 'Frases prohibidas',
        placeholder: 'Expresiones que el agente nunca debe usar',
        kind: 'textarea',
      },
    ],
  },
  {
    id: 3,
    title: 'Datos factuales',
    fields: [
      { key: 'business_hours', label: 'Horario de atención', placeholder: 'L-V 9:00-18:00' },
      { key: 'support_email', label: 'Email soporte', placeholder: 'soporte@tienda.com' },
      { key: 'support_phone', label: 'Teléfono soporte', placeholder: '+34 900 000 000' },
    ],
  },
  {
    id: 4,
    title: 'Conexión Shopify',
    fields: [],
  },
  {
    id: 5,
    title: 'Conexión helpdesk',
    fields: [],
  },
  {
    id: 6,
    title: 'Base de conocimiento inicial',
    fields: [],
  },
  {
    id: 7,
    title: 'Legal',
    fields: [
      { key: 'dpa_confirmed', label: 'DPA revisado', kind: 'checkbox' },
      { key: 'terms_confirmed', label: 'Términos aceptados', kind: 'checkbox' },
      { key: 'gdpr_confirmed', label: 'Consentimiento GDPR confirmado', kind: 'checkbox' },
    ],
  },
  {
    id: 8,
    title: 'Llamada de arranque',
    fields: [
      {
        key: 'call_preference',
        label: 'Preferencia de llamada',
        placeholder: 'Mañanas, tardes, días',
      },
      { key: 'call_notes', label: 'Temas para la llamada', kind: 'textarea' },
    ],
  },
  {
    id: 9,
    title: 'Confirmación',
    fields: [
      {
        key: 'launch_notes',
        label: 'Notas finales',
        placeholder: 'Algo que Auyan deba saber antes de empezar la construcción del agente',
        kind: 'textarea',
      },
    ],
  },
]

type StepValues = Record<string, string | boolean>
type StepData = Record<string, StepValues>

function normalizeStepData(data: Record<string, unknown>): StepData {
  return Object.fromEntries(
    Object.entries(data).map(([key, value]) => [
      key,
      value && typeof value === 'object' && !Array.isArray(value) ? (value as StepValues) : {},
    ]),
  )
}

export function OnboardingWizard({ tenantId }: { tenantId: string }) {
  const { data, error, isLoading, isError } = useTenantOnboarding(tenantId)
  const checklistQuery = useTenantOnboardingChecklist(tenantId)
  const saveMutation = useSaveTenantOnboarding(tenantId)
  const submitMutation = useSubmitTenantOnboarding(tenantId)
  const [step, setStep] = useState(1)
  const [stepData, setStepData] = useState<StepData>({})
  const [saveState, setSaveState] = useState<'idle' | 'saved' | 'error'>('idle')

  useEffect(() => {
    if (!data) return
    setStep(data.current_step)
    setStepData(normalizeStepData(data.step_data))
  }, [data])

  const completedSteps = useMemo(() => {
    const completed = new Set<number>(data?.completed_steps ?? [])
    for (const item of STEPS) {
      const values = stepData[String(item.id)] ?? {}
      const hasValue = item.fields.some((field) => Boolean(values[field.key]))
      if (hasValue) completed.add(item.id)
    }
    // Steps 4/5/6 ya no tienen fields — su completitud viene del checklist real.
    const checklist = checklistQuery.data
    if (checklist?.has_commerce_integration) completed.add(4)
    if (checklist?.has_helpdesk_integration) completed.add(5)
    if (checklist?.has_knowledge) completed.add(6)
    return [...completed].sort((a, b) => a - b)
  }, [data?.completed_steps, stepData, checklistQuery.data])

  const activeStep = STEPS[step - 1]
  const activeValues = stepData[String(step)] ?? {}
  const progress = Math.round((completedSteps.length / STEPS.length) * 100)
  const submitted = Boolean(data?.submitted_at)

  function updateField(field: Field, value: string | boolean) {
    setSaveState('idle')
    setStepData((current) => ({
      ...current,
      [String(step)]: {
        ...(current[String(step)] ?? {}),
        [field.key]: value,
      },
    }))
  }

  async function save(nextStep?: number) {
    try {
      const targetStep = nextStep ?? step
      await saveMutation.mutateAsync({
        current_step: targetStep,
        completed_steps: completedSteps,
        step_data: stepData,
      })
      setStep(targetStep)
      setSaveState('saved')
    } catch {
      setSaveState('error')
    }
  }

  async function submit() {
    await save(9)
    await submitMutation.mutateAsync()
  }

  if (isLoading) return <Skeleton className="h-[620px]" />

  if (isError || !data) {
    return (
      <div className="rounded-md border border-danger bg-danger-subtle px-4 py-3 text-sm text-danger-foreground">
        No se pudo cargar el onboarding.
        {error instanceof Error && <span className="mt-1 block">{error.message}</span>}
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
      <Card className="h-fit p-(--density-card-p)">
        <div className="flex items-end justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
              Progreso
            </p>
            <p className="mt-1 text-3xl font-semibold text-foreground">{progress}%</p>
          </div>
          {submitted && (
            <span className="rounded-sm bg-success-subtle px-2 py-1 text-xs font-medium text-success-foreground">
              Enviado
            </span>
          )}
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-muted">
          <div className="h-full bg-accent transition-all" style={{ width: `${progress}%` }} />
        </div>
        <nav className="mt-5 space-y-1">
          {STEPS.map((item) => {
            const active = item.id === step
            const done = completedSteps.includes(item.id)
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setStep(item.id)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm transition-colors',
                  active
                    ? 'bg-border-subtle font-medium text-foreground'
                    : 'text-foreground-body hover:bg-border-subtle',
                )}
              >
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-border text-[11px]">
                  {done ? <Check className="size-3" /> : item.id}
                </span>
                <span className="truncate">{item.title}</span>
              </button>
            )
          })}
        </nav>
      </Card>

      <Card className="p-(--density-card-p)">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
              Paso {activeStep.id} de {STEPS.length}
            </p>
            <h2 className="mt-1 text-xl font-semibold text-foreground">{activeStep.title}</h2>
          </div>
          <div className="flex items-center gap-2">
            {saveState === 'saved' && (
              <span className="text-xs text-success-foreground">Guardado</span>
            )}
            {saveState === 'error' && (
              <span className="text-xs text-danger-foreground">No se pudo guardar</span>
            )}
            <Button variant="outline" onClick={() => save()} disabled={saveMutation.isPending}>
              <Save className="size-4" />
              Guardar
            </Button>
          </div>
        </div>

        <div className="mt-5">
          <OnboardingChecklistBanner tenantId={tenantId} />
        </div>

        <div className="mt-6 grid gap-4">
          {step === 4 ? (
            <ShopifyConnectStep tenantId={tenantId} />
          ) : step === 5 ? (
            <HelpdeskConnectStep tenantId={tenantId} />
          ) : step === 6 ? (
            <KbUploadStep tenantId={tenantId} />
          ) : (
            activeStep.fields.map((field) => (
              <div key={field.key}>
                <Label htmlFor={field.key}>{field.label}</Label>
                {field.kind === 'textarea' ? (
                  <Textarea
                    id={field.key}
                    value={String(activeValues[field.key] ?? '')}
                    placeholder={field.placeholder}
                    onChange={(event) => updateField(field, event.target.value)}
                    className="mt-1.5 min-h-28"
                  />
                ) : field.kind === 'checkbox' ? (
                  <label className="mt-2 flex items-center gap-2 text-sm text-foreground-body">
                    <input
                      id={field.key}
                      type="checkbox"
                      checked={Boolean(activeValues[field.key])}
                      onChange={(event) => updateField(field, event.target.checked)}
                      className="size-4 rounded border-border accent-[var(--accent)]"
                    />
                    Confirmado
                  </label>
                ) : (
                  <Input
                    id={field.key}
                    value={String(activeValues[field.key] ?? '')}
                    placeholder={field.placeholder}
                    onChange={(event) => updateField(field, event.target.value)}
                    className="mt-1.5"
                  />
                )}
              </div>
            ))
          )}
        </div>

        <div className="mt-8 flex items-center justify-between border-t border-border-subtle pt-4">
          <Button
            variant="outline"
            disabled={step === 1}
            onClick={() => setStep((current) => Math.max(1, current - 1))}
          >
            <ArrowLeft className="size-4" />
            Anterior
          </Button>
          {step < 9 ? (
            <Button onClick={() => save(Math.min(9, step + 1))}>
              Siguiente
              <ArrowRight className="size-4" />
            </Button>
          ) : (
            <Button onClick={submit} disabled={submitted || submitMutation.isPending}>
              <Send className="size-4" />
              {submitted ? 'Enviado' : 'Enviar onboarding'}
            </Button>
          )}
        </div>
      </Card>
    </div>
  )
}
