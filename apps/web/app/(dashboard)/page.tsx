import { createClient } from '@/lib/supabase/server'
import { apiClient } from '@/lib/api/client'
import { redirect } from 'next/navigation'
import type { components } from '@auyan/shared/api-types'

type TenantResponse = components['schemas']['TenantResponse']

export default async function DashboardPage() {
  const supabase = await createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) redirect('/login')

  // Smoke test: GET /tenants/me funciona para tenant_admin/tenant_agent.
  // super_admin sin X-Tenant-Id → 403 del API.
  // openapi-fetch lanza excepción en errores de red (ECONNREFUSED, timeout) — catch obligatorio.
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
        <h1 className="text-xl font-semibold text-neutral-900">Dashboard</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Selecciona un tenant en el sidebar para ver sus conversaciones.
        </p>
      </div>

      {/* Sección de debug — solo en desarrollo */}
      {process.env.NODE_ENV === 'development' && (
        <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4 font-mono text-xs">
          <p className="mb-2 font-sans text-sm font-medium text-neutral-500">Debug — Auth + API</p>
          <div className="space-y-1 text-neutral-700">
            <p>
              <span className="text-neutral-400">usuario: </span>
              {session.user.email}
            </p>
            <p>
              <span className="text-neutral-400">token: </span>
              {session.access_token.slice(0, 24)}...
            </p>
          </div>
          <div className="mt-3 border-t border-neutral-200 pt-3">
            <p className="mb-1 font-sans text-sm font-medium text-neutral-500">
              GET /tenants/me
            </p>
            {tenant ? (
              <pre className="whitespace-pre-wrap text-green-700">
                {JSON.stringify(tenant, null, 2)}
              </pre>
            ) : (
              <p className="text-amber-600">
                {tenantErrorMsg ?? 'sin datos'}
                {' — '}
                <span className="text-neutral-500">
                  si eres super_admin, se necesita X-Tenant-Id (disponible en sub-PR 3.6)
                </span>
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
