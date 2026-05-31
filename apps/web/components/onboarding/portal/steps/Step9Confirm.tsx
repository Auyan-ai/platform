'use client'

import { CheckCircle2 } from 'lucide-react'
import { WizardCenteredLayout } from '../WizardLayouts'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import { useTenantOnboardingChecklist } from '@/lib/api/hooks/tenant-context'
import { Textarea } from '@/components/ui/textarea'
import type { StepProps } from './types'

export function Step9Confirm({ tenantId, values, onChange, onContinue }: StepProps) {
  const checklistQuery = useTenantOnboardingChecklist(tenantId)
  const checklist = checklistQuery.data

  const items: Array<{ done: boolean; label: string }> = [
    { done: checklist?.has_commerce_integration ?? false, label: 'Comercio conectado' },
    { done: checklist?.has_helpdesk_integration ?? false, label: 'Helpdesk conectado' },
    { done: checklist?.has_knowledge ?? false, label: 'Knowledge base inicial' },
  ]

  return (
    <WizardCenteredLayout>
      <WizardStepHeader
        title="Listo para enviar"
        subtitle="Auyan recibe tu onboarding y AIDE coordina contigo el arranque del agente."
      />

      <div className="mb-6 grid gap-2 rounded-md border border-border-subtle bg-surface-muted p-4">
        {items.map((item) => (
          <div
            key={item.label}
            className="flex items-center gap-2 text-sm text-foreground-body"
          >
            {item.done ? (
              <CheckCircle2 className="size-4 text-success" />
            ) : (
              <span className="size-4 rounded-full border border-border-strong" />
            )}
            <span className={item.done ? 'text-foreground' : 'text-foreground-muted'}>
              {item.label}
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

      <WizardStepActions onContinue={onContinue} continueLabel="Enviar onboarding" />
    </WizardCenteredLayout>
  )
}
