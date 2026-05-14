import { createClient } from '@/lib/supabase/server'
import { apiClient } from '@/lib/api/client'
import { redirect } from 'next/navigation'

export default async function DashboardPage() {
  const supabase = await createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) redirect('/login')

  // Smoke test: GET /tenants/me funciona para tenant_admin/tenant_agent.
  // super_admin sin X-Tenant-Id recibe 403 — lo mostramos en la UI sin crashear.
  const client = apiClient(session.access_token)
  const { data: tenant, error: tenantError } = await client.GET('/tenants/me')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-neutral-900">Dashboard</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Selecciona un tenant en el sidebar para ver sus conversaciones.
        </p>
      </div>

      {/* Sección de debug — mostrar solo en dev */}
      {process.env.NODE_ENV === 'development' && (
        <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4 text-xs font-mono">
          <p className="mb-2 text-neutral-500 font-sans text-sm font-medium">Debug — Auth + API</p>
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
          <div className="mt-3 pt-3 border-t border-neutral-200">
            <p className="mb-1 text-neutral-500 font-sans text-sm font-medium">
              GET /tenants/me
            </p>
            {tenant ? (
              <pre className="text-green-700 whitespace-pre-wrap">
                {JSON.stringify(tenant, null, 2)}
              </pre>
            ) : (
              <p className="text-amber-600">
                {JSON.stringify(tenantError) || 'sin datos'}
                {' — '}
                <span className="text-neutral-500">
                  si eres super_admin, selecciona un tenant para operar con X-Tenant-Id
                </span>
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
