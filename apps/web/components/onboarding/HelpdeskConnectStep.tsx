'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ChatwootConnectStep } from './ChatwootConnectStep'
import { GorgiasConnectStep } from './GorgiasConnectStep'
import { ZendeskConnectStep } from './ZendeskConnectStep'

export function HelpdeskConnectStep({ tenantId }: { tenantId: string }) {
  return (
    <div className="grid gap-4">
      <p className="text-sm text-foreground-muted">
        Conecta el helpdesk donde llegan los tickets de tus clientes. Chatwoot usa API
        token; Gorgias y Zendesk usan OAuth (un click, sin copiar credenciales).
      </p>

      <Tabs defaultValue="chatwoot">
        <TabsList>
          <TabsTrigger value="chatwoot">Chatwoot</TabsTrigger>
          <TabsTrigger value="gorgias">Gorgias</TabsTrigger>
          <TabsTrigger value="zendesk">Zendesk</TabsTrigger>
        </TabsList>

        <TabsContent value="chatwoot">
          <ChatwootConnectStep tenantId={tenantId} />
        </TabsContent>
        <TabsContent value="gorgias">
          <GorgiasConnectStep tenantId={tenantId} />
        </TabsContent>
        <TabsContent value="zendesk">
          <ZendeskConnectStep tenantId={tenantId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
