/**
 * Tipo común para todos los steps del wizard portal.
 * El parent (OnboardingPortal) maneja state + persistencia,
 * los steps son controlados.
 */
export type StepValues = Record<string, string | boolean | string[]>

export interface StepProps {
  values: StepValues
  onChange: (key: string, value: string | boolean | string[]) => void
  onContinue: () => void
  onBack?: () => void
  onSkip?: () => void
  tenantId: string
}
