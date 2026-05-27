import { createClient } from '@/lib/supabase/server'
import { apiClient } from '@/lib/api/client'
import { redirect } from 'next/navigation'
import { fetchCurrentUser } from '@/lib/api/users'
import { Card } from '@/components/ui/card'
import type { components } from '@auyan/shared/api-types'

type TenantResponse = components['schemas']['TenantResponse']

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

  // Smoke test: GET /tenants/me funciona para tenant_admin.
  // super_admin sin X-Tenant-Id → 403 del API.
  let tenant: TenantResponse | null = null
  let tenantErrorMsg: string | null = null
  try {
    const { data, error } = await apiClient(session.access_token).GET('/tenants/me')
    tenant = data ?? null
    if (error) tenantErrorMsg = JSON.stringify(error)
  } catch (e) {
    tenantErrorMsg = e instanceof Error ? e.message : 'Error de red al contactar el API'
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Dashboard</h1>
        <p className="mt-1 text-sm text-foreground-muted">
          Selecciona un tenant en el sidebar para ver sus conversaciones.
        </p>
      </div>

      {/* Sección de debug — solo en desarrollo */}
      {process.env.NODE_ENV === 'development' && (
        <Card className="bg-surface-muted p-4">
          <p className="mb-2 text-sm font-medium text-foreground-muted">Debug — Auth + API</p>
          <div className="space-y-1 text-xs font-mono text-foreground-body">
            <p>
              <span className="text-foreground-muted">usuario: </span>
              {session.user.email}
            </p>
            <p>
              <span className="text-foreground-muted">token: </span>
              {session.access_token.slice(0, 24)}…
            </p>
          </div>
          <div className="mt-3 border-t border-border-subtle pt-3">
            <p className="mb-1 text-sm font-medium text-foreground-muted">GET /tenants/me</p>
            {tenant ? (
              <pre className="whitespace-pre-wrap text-xs font-mono text-success-foreground">
                {JSON.stringify(tenant, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-warning-foreground">
                {tenantErrorMsg ?? 'sin datos'}
                {' — '}
                <span className="text-foreground-muted">
                  si eres super_admin, se necesita X-Tenant-Id (disponible en sub-PR 3.6)
                </span>
              </p>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
