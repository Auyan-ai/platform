'use client'

import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface WizardStepActionsProps {
  onContinue: () => void
  onBack?: () => void
  onSkip?: () => void
  continueLabel?: string
  skipLabel?: string
  continueDisabled?: boolean
  continueLoading?: boolean
  /** Si true, el botón "Anterior" se renderiza deshabilitado (útil para step 1). */
  backDisabled?: boolean
}

/**
 * Footer del step: Anterior (izq) · Skip + Continuar (der).
 * Patrón Linear: ghost links discretos, primary pill como CTA.
 */
export function WizardStepActions({
  onContinue,
  onBack,
  onSkip,
  continueLabel = 'Continuar',
  skipLabel = 'Skip por ahora',
  continueDisabled = false,
  continueLoading = false,
  backDisabled = false,
}: WizardStepActionsProps) {
  return (
    <div className="mt-6 flex items-center justify-between gap-4">
      <div>
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            disabled={backDisabled}
            className="inline-flex items-center gap-1 rounded-sm px-2 py-1.5 text-xs text-foreground-muted transition-colors hover:bg-surface-muted hover:text-foreground-body disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
          >
            <ArrowLeft className="size-3" />
            Anterior
          </button>
        )}
      </div>
      <div className="flex items-center gap-4">
        {onSkip && (
          <button
            type="button"
            onClick={onSkip}
            className="rounded-sm px-2 py-1.5 text-xs text-foreground-muted transition-colors hover:bg-surface-muted hover:text-foreground-body"
          >
            {skipLabel}
          </button>
        )}
        <Button onClick={onContinue} disabled={continueDisabled || continueLoading} size="default">
          {continueLoading ? 'Procesando...' : continueLabel}
        </Button>
      </div>
    </div>
  )
}
