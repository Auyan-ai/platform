import { ClientSidebar } from '@/components/clients/ClientSidebar'
import { AppTopbar } from '@/components/nav/AppTopbar'
import { apiClient } from '@/lib/api/client'
import { fetchCurrentUser } from '@/lib/api/users'
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import type { ReactNode } from 'react'

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
  let lifecycleState = 'initial'
  try {
    const { data } = await apiClient(session.access_token).GET('/tenants/me')
    if (data?.name) tenantName = data.name
    if (data?.agent_lifecycle_state) lifecycleState = data.agent_lifecycle_state
  } catch {
    // fallback: mostramos el tenant_id como nombre
  }

  // Tenant_admin con lifecycle initial/discovery → forzamos onboarding portal.
  // El portal mismo redirige de vuelta al dashboard cuando el lifecycle pasa a building+.
  if (lifecycleState === 'initial' || lifecycleState === 'discovery') {
    redirect('/onboarding')
  }

  return (
    <div data-density="relaxed" data-theme="mercury" className="min-h-screen bg-background">
      <ClientSidebar
        tenantId={user.tenant_id}
        tenantName={tenantName}
        lifecycleState={lifecycleState}
        userEmail={user.email}
      />
      <div className="ml-[200px] min-h-screen">
        <AppTopbar
          placeholder="Buscar secciones del cliente..."
          quickLinks={[
            {
              label: 'Home',
              href: `/clients/${user.tenant_id}/overview`,
              description: 'Resumen del cliente',
            },
            {
              label: 'Insights',
              href: `/clients/${user.tenant_id}/insights`,
              description: 'Conversaciones y métricas',
            },
            {
              label: 'Reportes',
              href: `/clients/${user.tenant_id}/reports`,
              description: 'Reportes semanales',
            },
            {
              label: 'Knowledge Base',
              href: `/clients/${user.tenant_id}/knowledge`,
              description: 'Documentos y fuentes',
            },
            {
              label: 'Aprobaciones',
              href: `/clients/${user.tenant_id}/approvals`,
              description: 'Acciones pendientes',
            },
            {
              label: 'Configuración',
              href: `/clients/${user.tenant_id}/settings`,
              description: 'Preferencias del cliente',
            },
          ]}
        />
        <main className="px-8 pb-10 pt-16">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  )
}
