import { ClientHomeSummary } from '@/components/clients/ClientHomeSummary'
import { MetricsCards } from '@/components/clients/MetricsCards'
import { RecentConversations } from '@/components/clients/RecentConversations'
import { UsageCard } from '@/components/clients/UsageCard'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientOverviewPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-8">
      <ClientHomeSummary tenantId={tenantId} />

      <MetricsCards tenantId={tenantId} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <UsageCard tenantId={tenantId} />
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-foreground">Conversaciones recientes</h2>
        <RecentConversations tenantId={tenantId} />
      </div>
    </div>
  )
}
