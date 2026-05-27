import { MetricsCards } from '@/components/clients/MetricsCards'
import { RecentConversations } from '@/components/clients/RecentConversations'
import { UsageCard } from '@/components/clients/UsageCard'
import { Button } from '@/components/ui/button'
import { MessageSquarePlus, Upload, Wand2 } from 'lucide-react'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientOverviewPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Bienvenido</h1>
          <p className="mt-1 text-sm text-foreground-muted">
            Estado operativo del soporte IA de tu cuenta.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm">
            <MessageSquarePlus className="size-4" />
            Revisar inbox
          </Button>
          <Button size="sm" variant="secondary">
            <Upload className="size-4" />
            Subir KB
          </Button>
          <Button size="sm" variant="secondary">
            <Wand2 className="size-4" />
            Pedir ajuste
          </Button>
        </div>
      </div>

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
