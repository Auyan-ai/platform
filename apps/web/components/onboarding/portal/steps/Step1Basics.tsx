'use client'

import { useState } from 'react'
import { WizardCenteredLayout } from '../WizardLayouts'
import { WizardInput } from '../WizardInput'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import type { StepProps } from './types'

const TICKET_RANGES = ['1.000 - 3.000', '3.000 - 10.000', '10.000 - 30.000', '+30.000']

export function Step1Basics({ values, onChange, onContinue, onBack }: StepProps) {
  const [errors, setErrors] = useState<string | null>(null)

  function handleContinue() {
    const name = String(values.company_name ?? '').trim()
    const web = String(values.website_url ?? '').trim()
    if (!name || !web) {
      setErrors('Nombre y web son obligatorios.')
      return
    }
    setErrors(null)
    onContinue()
  }

  return (
    <WizardCenteredLayout>
      <WizardStepHeader
        title="Cuéntanos de tu tienda"
        subtitle="Empecemos por lo más básico."
      />
      <div className="grid gap-5">
        <WizardInput
          label="Nombre comercial"
          placeholder="Marea Studio"
          value={String(values.company_name ?? '')}
          onChange={(e) => onChange('company_name', e.target.value)}
        />
        <WizardInput
          label="Web de la tienda"
          placeholder="https://mareastudio.com"
          value={String(values.website_url ?? '')}
          onChange={(e) => onChange('website_url', e.target.value)}
        />
        <WizardInput
          label="Persona de contacto"
          placeholder="María García, CX Lead"
          value={String(values.primary_contact ?? '')}
          onChange={(e) => onChange('primary_contact', e.target.value)}
        />
        <div>
          <label
            htmlFor="support_volume"
            className="mb-1.5 block text-xs font-normal text-foreground-muted"
          >
            Volumen mensual de tickets
          </label>
          <select
            id="support_volume"
            value={String(values.support_volume ?? TICKET_RANGES[0])}
            onChange={(e) => onChange('support_volume', e.target.value)}
            className="flex h-9 w-full appearance-none rounded-sm border border-transparent bg-surface-muted bg-no-repeat px-3 pr-9 text-sm text-foreground transition-colors hover:bg-[#EEECEA] focus:bg-surface focus:border-accent focus:outline focus:outline-2 focus:outline-accent focus:outline-offset-2"
            style={{
              backgroundImage:
                "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2378716C' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'></polyline></svg>\")",
              backgroundPosition: 'right 12px center',
            }}
          >
            {TICKET_RANGES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>
      {errors && <p className="mt-3 text-sm text-danger-foreground">{errors}</p>}
      <WizardStepActions onContinue={handleContinue} onBack={onBack} />
    </WizardCenteredLayout>
  )
}
