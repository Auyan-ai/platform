import type { ReactNode } from 'react'
import { WizardTopnav } from './WizardTopnav'
import { WizardProgress } from './WizardProgress'
import { WizardFooter } from './WizardFooter'

interface PortalShellProps {
  totalSteps: number
  currentStep: number
  completedSteps: number[]
  userEmail: string
  children: ReactNode
}

/**
 * Shell del onboarding portal full-screen.
 * Topnav (logo) + body + progress dots + footer (sesión + logout).
 * Sin sidebar, sin AppTopbar, sin distracciones.
 */
export function PortalShell({
  totalSteps,
  currentStep,
  completedSteps,
  userEmail,
  children,
}: PortalShellProps) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <WizardTopnav />
      <main className="flex flex-1 flex-col">{children}</main>
      <WizardProgress
        totalSteps={totalSteps}
        currentStep={currentStep}
        completedSteps={completedSteps}
      />
      <WizardFooter userEmail={userEmail} />
    </div>
  )
}
