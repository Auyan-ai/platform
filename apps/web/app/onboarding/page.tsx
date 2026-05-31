import { createClient } from '@/lib/supabase/server'
import { fetchCurrentUser } from '@/lib/api/users'
import { redirect } from 'next/navigation'
import { OnboardingPortal } from '@/components/onboarding/portal/OnboardingPortal'

/**
 * Onboarding portal — entry point para tenant_admin con onboarding incompleto.
 *
 * Auth: requiere session válida + role tenant_admin con tenant_id.
 * Super_admin que llegue aquí por error se va al dashboard.
 */
export default async function OnboardingPage() {
  const supabase = await createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) redirect('/login')

  const user = await fetchCurrentUser(session.access_token)

  if (!user) redirect('/login')

  // Super_admin no usa este flujo — su trabajo es operar tenants, no onboardearse.
  if (user.role === 'super_admin') redirect('/')

  if (user.role !== 'tenant_admin' || !user.tenant_id) {
    redirect('/login')
  }

  return (
    <OnboardingPortal
      tenantId={user.tenant_id}
      userEmail={user.email}
      dashboardUrl={`/clients/${user.tenant_id}/overview`}
    />
  )
}
