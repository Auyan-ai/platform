import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientOnboardingPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Activación
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Onboarding</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Completa la información inicial para que Auyan prepare el agente y pase a Building.
        </p>
      </div>

      <OnboardingWizard tenantId={tenantId} />
    </div>
  )
}
