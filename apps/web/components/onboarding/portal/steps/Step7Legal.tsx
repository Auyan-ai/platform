'use client'

import { useState } from 'react'
import { WizardCenteredLayout } from '../WizardLayouts'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import type { StepProps } from './types'

const LEGAL_ITEMS: Array<{ key: string; label: string }> = [
  { key: 'dpa_confirmed', label: 'He revisado el Data Processing Agreement (DPA) de Auyan.' },
  { key: 'terms_confirmed', label: 'He aceptado los Términos del Servicio.' },
  { key: 'gdpr_confirmed', label: 'Confirmo el consentimiento GDPR para procesamiento de datos de mis clientes.' },
]

export function Step7Legal({ values, onChange, onContinue, onBack }: StepProps) {
  const [error, setError] = useState<string | null>(null)

  function handleContinue() {
    const missing = LEGAL_ITEMS.filter((item) => !values[item.key])
    if (missing.length > 0) {
      setError('Confirma los tres puntos para continuar.')
      return
    }
    setError(null)
    onContinue()
  }

  return (
    <WizardCenteredLayout>
      <WizardStepHeader
        title="Legal"
        subtitle="Tres confirmaciones rápidas antes de que el agente toque datos de tus clientes."
      />
      <div className="grid gap-3">
        {LEGAL_ITEMS.map((item) => (
          <label
            key={item.key}
            className="flex cursor-pointer items-start gap-3 rounded-sm bg-surface-muted px-3 py-3 text-sm text-foreground-body transition-colors hover:bg-[#EEECEA]"
          >
            <input
              type="checkbox"
              checked={Boolean(values[item.key])}
              onChange={(e) => onChange(item.key, e.target.checked)}
              className="mt-0.5 size-4 shrink-0 rounded border-border accent-[var(--accent)]"
            />
            <span>{item.label}</span>
          </label>
        ))}
      </div>
      {error && <p className="mt-3 text-sm text-danger-foreground">{error}</p>}
      <WizardStepActions onContinue={handleContinue} onBack={onBack} />
    </WizardCenteredLayout>
  )
}
