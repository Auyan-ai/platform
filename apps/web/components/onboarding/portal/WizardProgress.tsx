import { cn } from '@/lib/utils'

interface WizardProgressProps {
  totalSteps: number
  currentStep: number
  completedSteps: number[]
}

/**
 * Dots de progreso debajo del wizard.
 * - Done: foreground-muted
 * - Active: cobalto, más ancho (24px)
 * - Pending: border-strong
 */
export function WizardProgress({ totalSteps, currentStep, completedSteps }: WizardProgressProps) {
  return (
    <div className="flex items-center justify-center gap-1.5 pt-6 pb-4">
      {Array.from({ length: totalSteps }, (_, i) => {
        const stepNum = i + 1
        const isActive = stepNum === currentStep
        const isDone = completedSteps.includes(stepNum) && !isActive
        return (
          <span
            key={stepNum}
            className={cn(
              'h-1.5 rounded-full transition-all duration-200',
              isActive ? 'w-6 bg-accent' : 'w-1.5',
              isDone && 'bg-foreground-muted',
              !isActive && !isDone && 'bg-border-strong',
            )}
          />
        )
      })}
    </div>
  )
}
