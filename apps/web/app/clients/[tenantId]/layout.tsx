import type { ReactNode } from 'react'
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { fetchCurrentUser } from '@/lib/api/users'
import { apiClient } from '@/lib/api/client'
import { ClientSidebar } from '@/components/clients/ClientSidebar'
import { AppTopbar } from '@/components/nav/AppTopbar'

interface Props {
  children: ReactNode
  params: Promise<{ tenantId: string }>
}

export default async function ClientsLayout({ children, params }: Props) {
  const { tenantId: urlTenantId } = await params

  const supabase = await createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) redirect('/login')

  const user = await fetchCurrentUser(session.access_token)

  if (!user || user.role !== 'tenant_admin' || !user.tenant_id) {
    redirect('/')
  }

  // AISLAMIENTO DE TENANT: el tenantId de la URL debe coincidir con el del usuario.
  // Sin esta verificación, un tenant_admin podría ver datos de otro tenant.
  if (urlTenantId !== user.tenant_id) {
    redirect(`/clients/${user.tenant_id}/overview`)
  }

  let tenantName = user.tenant_id
  try {
    const { data } = await apiClient(session.access_token).GET('/tenants/me')
    if (data?.name) tenantName = data.name
  } catch {
    // fallback: mostramos el tenant_id como nombre
  }

  return (
    <div data-density="relaxed" data-theme="mercury" className="min-h-screen bg-background">
      <ClientSidebar tenantId={user.tenant_id} tenantName={tenantName} userEmail={user.email} />
      <div className="ml-[200px] min-h-screen">
        <AppTopbar actionLabel="Solicitar revisión" />
        <main className="px-8 pb-10 pt-16">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  )
}
