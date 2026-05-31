'use client'

import { Button } from '@/components/ui/button'

interface WizardStepActionsProps {
  onContinue: () => void
  onSkip?: () => void
  continueLabel?: string
  skipLabel?: string
  continueDisabled?: boolean
  continueLoading?: boolean
}

/**
 * Footer del step: Skip a la izquierda, Continuar a la derecha.
 * Patrón Linear: skip text-link, continue primary pill.
 */
export function WizardStepActions({
  onContinue,
  onSkip,
  continueLabel = 'Continuar',
  skipLabel = 'Skip por ahora',
  continueDisabled = false,
  continueLoading = false,
}: WizardStepActionsProps) {
  return (
    <div className="mt-6 flex items-center justify-end gap-4">
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
  )
}
