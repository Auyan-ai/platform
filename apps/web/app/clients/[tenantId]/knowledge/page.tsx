import { ClientKnowledgeBase } from '@/components/knowledge/ClientKnowledgeBase'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientKnowledgePage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Knowledge base
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Conocimiento</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Envía contenido para que Auyan lo revise antes de incorporarlo al agente.
        </p>
      </div>

      <ClientKnowledgeBase tenantId={tenantId} />
    </div>
  )
}
