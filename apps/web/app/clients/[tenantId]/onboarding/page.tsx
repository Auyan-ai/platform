import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard'
import { apiClient } from '@/lib/api/client'
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientOnboardingPage({ params }: Props) {
  const { tenantId } = await params
  const supabase = await createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) redirect('/login')

  let lifecycleState = 'initial'
  try {
    const { data } = await apiClient(session.access_token).GET('/tenants/me')
    if (data?.agent_lifecycle_state) lifecycleState = data.agent_lifecycle_state
  } catch {
    // Layout handles auth and tenant isolation; keep the form accessible if this read fails.
  }

  if (lifecycleState !== 'initial') redirect(`/clients/${tenantId}/overview`)

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
