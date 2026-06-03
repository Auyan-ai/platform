import { DashboardShell } from '@/components/nav/DashboardShell'
import { fetchCurrentUser } from '@/lib/api/users'
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import type { ReactNode } from 'react'

export default async function DashboardLayout({ children }: { children: ReactNode }) {
  const supabase = await createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) {
    redirect('/login')
  }

  // GATE DE ROL: el dashboard interno es cross-tenant y solo para super_admin
  // (operador Auyan). Sin esta verificación, cualquier usuario autenticado —
  // incluido un tenant_admin — podía renderizar el cockpit interno. Un
  // tenant_admin se redirige a su propio dashboard de cliente.
  const user = await fetchCurrentUser(session.access_token)
  if (!user || user.role !== 'super_admin') {
    if (user?.role === 'tenant_admin' && user.tenant_id) {
      redirect(`/clients/${user.tenant_id}/overview`)
    }
    redirect('/login')
  }

  return <DashboardShell userEmail={user.email}>{children}</DashboardShell>
}
