import { ClientKnowledgeBase } from '@/components/knowledge/ClientKnowledgeBase'
import { PendingConfirmationBanner } from '@/components/knowledge/PendingConfirmationBanner'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientKnowledgePage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Base de conocimiento
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Base de conocimiento</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Envía documentos y fuentes para que Auyan los revise antes de incorporarlos al agente.
        </p>
      </div>

      <PendingConfirmationBanner tenantId={tenantId} />
      <ClientKnowledgeBase tenantId={tenantId} />
    </div>
  )
}
