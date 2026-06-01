'use client'

import { CheckCircle2, Circle } from 'lucide-react'
import { WizardCenteredLayout } from '../WizardLayouts'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import {
  useTenantOnboarding,
  useTenantOnboardingChecklist,
} from '@/lib/api/hooks/tenant-context'
import { Textarea } from '@/components/ui/textarea'
import type { StepProps } from './types'

export function Step9Confirm({ tenantId, values, onChange, onContinue, onBack }: StepProps) {
  const onboardingQuery = useTenantOnboarding(tenantId)
  const checklistQuery = useTenantOnboardingChecklist(tenantId)
  const checklist = checklistQuery.data
  const isSubmitted = Boolean(onboardingQuery.data?.submitted_at)

  // Items "gateables" del checklist (los 4 que bloquean discovery → building).
  // onboarding_submitted no se lista porque es justo lo que el cliente está
  // haciendo en este step.
  const gates: Array<{ done: boolean; label: string; help?: string }> = [
    {
      done: checklist?.has_commerce_integration ?? false,
      label: 'Comercio conectado',
      help: 'Volver al paso 4 para conectar Shopify',
    },
    {
      done: checklist?.has_helpdesk_integration ?? false,
      label: 'Helpdesk conectado',
      help: 'Volver al paso 5 para conectar Chatwoot, Gorgias o Zendesk',
    },
    {
      done: checklist?.has_knowledge ?? false,
      label: 'Knowledge base inicial',
      help: 'Volver al paso 6 para subir al menos un documento',
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
        <div className="mb-6 grid gap-2 rounded-md border border-warning bg-warning-subtle p-4">
          {gates.map((g) => (
            <div key={g.label} className="flex items-start gap-3 text-sm">
              {g.done ? (
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
              ) : (
                <Circle className="mt-0.5 size-4 shrink-0 text-foreground-muted" />
              )}
              <div>
                <div className={g.done ? 'text-foreground' : 'text-foreground'}>
                  {g.label}
                </div>
                {!g.done && g.help && (
                  <div className="text-xs text-foreground-muted">{g.help}</div>
                )}
              </div>
            </div>
          ))}
        </div>
        <p className="text-sm text-foreground-muted">
          Completa los gates faltantes y volvemos a evaluar automáticamente. Si
          quieres seguir luego, cierra esta pestaña y vuelve cuando puedas — tu
          progreso queda guardado.
        </p>
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
