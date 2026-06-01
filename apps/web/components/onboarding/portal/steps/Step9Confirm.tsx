'use client'

import { ArrowLeft, CheckCircle2, Circle } from 'lucide-react'
import { WizardCenteredLayout } from '../WizardLayouts'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import { Button } from '@/components/ui/button'
import {
  useTenantOnboarding,
  useTenantOnboardingChecklist,
} from '@/lib/api/hooks/tenant-context'
import { Textarea } from '@/components/ui/textarea'
import type { StepProps } from './types'

export function Step9Confirm({
  tenantId,
  values,
  onChange,
  onContinue,
  onBack,
  onGoToStep,
}: StepProps) {
  const onboardingQuery = useTenantOnboarding(tenantId)
  const checklistQuery = useTenantOnboardingChecklist(tenantId)
  const checklist = checklistQuery.data
  const isSubmitted = Boolean(onboardingQuery.data?.submitted_at)

  // Gates del checklist con jump directo al step responsable.
  const gates: Array<{
    done: boolean
    label: string
    targetStep: number
    targetLabel: string
  }> = [
    {
      done: checklist?.has_commerce_integration ?? false,
      label: 'Comercio conectado',
      targetStep: 4,
      targetLabel: 'Ir al paso 4 · Shopify',
    },
    {
      done: checklist?.has_helpdesk_integration ?? false,
      label: 'Helpdesk conectado',
      targetStep: 5,
      targetLabel: 'Ir al paso 5 · Helpdesk',
    },
    {
      done: checklist?.has_knowledge ?? false,
      label: 'Knowledge base inicial',
      targetStep: 6,
      targetLabel: 'Ir al paso 6 · KB',
    },
  ]

  const allDone = gates.every((g) => g.done)

  // Después de enviar: si el lifecycle ya pasó a building, el portal redirige
  // automáticamente al dashboard. Si NO, es porque algún gate falta — mostramos
  // qué hacer.
  if (isSubmitted && !allDone) {
    return (
      <WizardCenteredLayout>
        <WizardStepHeader
          title="Onboarding enviado · faltan gates"
          subtitle="Recibimos tu onboarding. Para que el agente arranque (lifecycle Building) falta completar:"
        />
        <div className="mb-6 grid gap-3 rounded-md border border-warning bg-warning-subtle p-4">
          {gates.map((g) => (
            <div key={g.label} className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 text-sm">
                {g.done ? (
                  <CheckCircle2 className="size-4 shrink-0 text-success" />
                ) : (
                  <Circle className="size-4 shrink-0 text-foreground-muted" />
                )}
                <span className="text-foreground">{g.label}</span>
              </div>
              {!g.done && onGoToStep && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onGoToStep(g.targetStep)}
                >
                  {g.targetLabel}
                </Button>
              )}
            </div>
          ))}
        </div>
        <p className="text-sm text-foreground-muted">
          Completa los gates faltantes y volvemos a evaluar automáticamente.
          Tu progreso queda guardado si cierras la pestaña.
        </p>
        {onBack && (
          <div className="mt-6 flex justify-start">
            <button
              type="button"
              onClick={onBack}
              className="inline-flex items-center gap-1 rounded-sm px-2 py-1.5 text-xs text-foreground-muted transition-colors hover:bg-surface-muted hover:text-foreground-body"
            >
              <ArrowLeft className="size-3" />
              Anterior
            </button>
          </div>
        )}
      </WizardCenteredLayout>
    )
  }

  return (
    <WizardCenteredLayout>
      <WizardStepHeader
        title={isSubmitted ? 'Onboarding enviado' : 'Listo para enviar'}
        subtitle={
          isSubmitted
            ? 'Auyan recibió tu onboarding. Si el checklist está completo, el agente entra en Building automáticamente.'
            : 'Auyan recibe tu onboarding y AIDE coordina contigo el arranque del agente.'
        }
      />

      <div className="mb-6 grid gap-2 rounded-md border border-border-subtle bg-surface-muted p-4">
        {gates.map((g) => (
          <div key={g.label} className="flex items-center gap-2 text-sm text-foreground-body">
            {g.done ? (
              <CheckCircle2 className="size-4 text-success" />
            ) : (
              <Circle className="size-4 text-foreground-muted" />
            )}
            <span className={g.done ? 'text-foreground' : 'text-foreground-muted'}>
              {g.label}
            </span>
          </div>
        ))}
      </div>

      <div>
        <label
          htmlFor="launch_notes"
          className="mb-1.5 block text-xs font-normal text-foreground-muted"
        >
          Algo más que Auyan deba saber (opcional)
        </label>
        <Textarea
          id="launch_notes"
          placeholder="Picos estacionales, lanzamientos pronto, casos extremos, etc."
          value={String(values.launch_notes ?? '')}
          onChange={(e) => onChange('launch_notes', e.target.value)}
          className="min-h-20 border-transparent bg-surface-muted text-sm hover:bg-[#EEECEA] focus-visible:bg-surface focus-visible:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
        />
      </div>

      {!isSubmitted && (
        <WizardStepActions
          onContinue={onContinue}
          onBack={onBack}
          continueLabel="Enviar onboarding"
        />
      )}
    </WizardCenteredLayout>
  )
}
