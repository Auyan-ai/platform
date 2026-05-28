import { ReviewQueueHome } from '@/components/dashboard/ReviewQueueHome'
import { fetchCurrentUser } from '@/lib/api/users'
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'

export default async function DashboardPage() {
  const supabase = await createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) redirect('/login')

  // Redirect de rol server-side — más confiable que desde el cliente (sin CORS)
  const currentUser = await fetchCurrentUser(session.access_token)
  if (currentUser?.role === 'tenant_admin' && currentUser.tenant_id) {
    redirect(`/clients/${currentUser.tenant_id}/overview`)
  }

  return <ReviewQueueHome />
}
