'use client'

import { WizardSplitLayout } from '../WizardLayouts'
import { WizardInput } from '../WizardInput'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import { Textarea } from '@/components/ui/textarea'
import type { StepProps } from './types'

export function Step8Call({ values, onChange, onContinue, onSkip, onBack }: StepProps) {
  return (
    <WizardSplitLayout>
      <WizardStepHeader
        title="Call con AIDE"
        subtitle="Tu Agent Implementation & Deployment Engineer revisa el contexto, define los AOPs y arranca el agente. ~45 minutos."
      />
      <div className="grid gap-4">
        <WizardInput
          label="Preferencia de horario"
          placeholder="Mañanas L-V, zona horaria Madrid"
          value={String(values.call_preference ?? '')}
          onChange={(e) => onChange('call_preference', e.target.value)}
        />
        <div>
          <label
            htmlFor="call_notes"
            className="mb-1.5 block text-xs font-normal text-foreground-muted"
          >
            Temas que quieres cubrir (opcional)
          </label>
          <Textarea
            id="call_notes"
            placeholder="Casos atípicos del CX, integraciones que faltan, dudas sobre el flujo del agente..."
            value={String(values.call_notes ?? '')}
            onChange={(e) => onChange('call_notes', e.target.value)}
            className="min-h-24 border-transparent bg-surface-muted text-sm hover:bg-[#EEECEA] focus-visible:bg-surface focus-visible:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          />
        </div>
      </div>
      <WizardStepActions onContinue={onContinue} onBack={onBack} onSkip={onSkip} />
    </WizardSplitLayout>
  )
}
