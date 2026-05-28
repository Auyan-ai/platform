import { KnowledgeReviewQueue } from '@/components/knowledge/KnowledgeReviewQueue'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function TenantKnowledgePage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Knowledge ops
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">KB pending review</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Revisa contenidos aportados por el cliente antes de indexarlos en la KB del agente.
        </p>
      </div>

      <KnowledgeReviewQueue tenantId={tenantId} />
    </div>
  )
}
