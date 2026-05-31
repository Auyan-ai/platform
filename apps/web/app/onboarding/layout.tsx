import type { ReactNode } from 'react'

/**
 * Layout dedicado del onboarding portal — sin sidebar, sin AppTopbar.
 * El cliente está enfocado en una sola cosa: completar el wizard.
 *
 * Densidad relaxed (cliente). Tema Mercury heredado.
 */
export default function OnboardingLayout({ children }: { children: ReactNode }) {
  return (
    <div data-density="relaxed" data-theme="mercury" className="min-h-screen bg-background">
      {children}
    </div>
  )
}
