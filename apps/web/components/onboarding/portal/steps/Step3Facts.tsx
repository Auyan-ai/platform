'use client'

import { WizardSplitLayout } from '../WizardLayouts'
import { WizardInput } from '../WizardInput'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import type { StepProps } from './types'

export function Step3Facts({ values, onChange, onContinue, onBack }: StepProps) {
  return (
    <WizardSplitLayout>
      <WizardStepHeader
        title="Tu tienda en datos concretos"
        subtitle="El agente cita estos datos textualmente cuando un cliente pregunta. Si algo cambia, lo actualizas aquí."
      />
      <div className="grid gap-5">
        <WizardInput
          label="Horario de atención"
          placeholder="L-V 9:00-18:00 (CET)"
          value={String(values.business_hours ?? '')}
          onChange={(e) => onChange('business_hours', e.target.value)}
        />
        <WizardInput
          label="Email de soporte"
          placeholder="soporte@mareastudio.com"
          value={String(values.support_email ?? '')}
          onChange={(e) => onChange('support_email', e.target.value)}
        />
        <WizardInput
          label="Teléfono de soporte (opcional)"
          placeholder="+34 900 123 456"
          value={String(values.support_phone ?? '')}
          onChange={(e) => onChange('support_phone', e.target.value)}
        />
        <WizardInput
          label="Ventana de devolución"
          placeholder="30 días desde la entrega"
          value={String(values.return_window_days ?? '')}
          onChange={(e) => onChange('return_window_days', e.target.value)}
        />
      </div>
      <WizardStepActions onContinue={onContinue} onBack={onBack} />
    </WizardSplitLayout>
  )
}
