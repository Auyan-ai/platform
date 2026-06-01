'use client'

import { WizardSplitLayout } from '../WizardLayouts'
import { WizardStepHeader } from '../WizardStepHeader'
import { WizardStepActions } from '../WizardStepActions'
import { Textarea } from '@/components/ui/textarea'
import type { StepProps } from './types'

export function Step2Voice({ values, onChange, onContinue, onBack }: StepProps) {
  return (
    <WizardSplitLayout>
      <WizardStepHeader
        title="¿Cómo habla tu marca?"
        subtitle="El agente adopta este tono en cada respuesta. Sé específico."
      />
      <div className="grid gap-5">
        <div>
          <label
            htmlFor="voice_traits"
            className="mb-1.5 block text-xs font-normal text-foreground-muted"
          >
            Tono deseado
          </label>
          <Textarea
            id="voice_traits"
            placeholder="Cercano, claro, resolutivo. Sin sonar robótico ni demasiado formal."
            value={String(values.voice_traits ?? '')}
            onChange={(e) => onChange('voice_traits', e.target.value)}
            className="min-h-24 border-transparent bg-surface-muted text-sm hover:bg-[#EEECEA] focus-visible:bg-surface focus-visible:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          />
        </div>
        <div>
          <label
            htmlFor="forbidden_phrases"
            className="mb-1.5 block text-xs font-normal text-foreground-muted"
          >
            Frases prohibidas
          </label>
          <Textarea
            id="forbidden_phrases"
            placeholder="Cosas que el agente nunca debe decir. Una por línea."
            value={String(values.forbidden_phrases ?? '')}
            onChange={(e) => onChange('forbidden_phrases', e.target.value)}
            className="min-h-20 border-transparent bg-surface-muted text-sm hover:bg-[#EEECEA] focus-visible:bg-surface focus-visible:border-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2"
          />
        </div>
      </div>
      <WizardStepActions onContinue={onContinue} onBack={onBack} />
    </WizardSplitLayout>
  )
}
