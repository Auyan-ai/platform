'use client'

import { PromoteDemoDialog } from '@/components/dashboard/PromoteDemoDialog'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useAdminTenants } from '@/lib/api/hooks/tenants'
import { demoBadgeLabel, isDemo } from '@/lib/demo'

/** Cabecera de la ficha de una demo: insignia de caducidad y "Convertir en cliente".
 * Desaparece sola cuando el tenant deja de ser demo (la lista se invalida al convertir). */
export function DemoTenantBar({ tenantId }: { tenantId: string }) {
  const { data: tenants } = useAdminTenants()
  const tenant = tenants?.find((t) => t.id === tenantId)
  if (!tenant || !isDemo(tenant)) return null

  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 p-(--density-card-p)">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-foreground">{tenant.name}</p>
          <Badge variant="warning">{demoBadgeLabel(tenant.demo_expires_at)}</Badge>
        </div>
        <p className="truncate text-xs text-foreground-muted">
          {tenant.demo_source_url ?? tenant.slug}
        </p>
      </div>
      <PromoteDemoDialog tenantId={tenant.id} tenantName={tenant.name} />
    </Card>
  )
}
