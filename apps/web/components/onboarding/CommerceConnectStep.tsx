'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ShopifyConnectStep } from './ShopifyConnectStep'
import { WooCommerceConnectStep } from './WooCommerceConnectStep'

export function CommerceConnectStep({ tenantId }: { tenantId: string }) {
  return (
    <div className="grid gap-4">
      <p className="text-sm text-foreground-muted">
        Conecta la tienda donde están los pedidos. El agente consulta pedidos y, con tu
        aprobación, cancela, reembolsa o cambia la dirección de envío.
      </p>

      <Tabs defaultValue="shopify">
        <TabsList>
          <TabsTrigger value="shopify">Shopify</TabsTrigger>
          <TabsTrigger value="woocommerce">WooCommerce</TabsTrigger>
        </TabsList>

        <TabsContent value="shopify">
          <ShopifyConnectStep tenantId={tenantId} />
        </TabsContent>
        <TabsContent value="woocommerce">
          <WooCommerceConnectStep tenantId={tenantId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
