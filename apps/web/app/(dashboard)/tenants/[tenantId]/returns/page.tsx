import { ReturnsPolicyForm } from '@/components/returns-policy/ReturnsPolicyForm'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function TenantReturnsPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Knowledge ops
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Devoluciones y cambios</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Política que el cliente decide y el agente aplica en código. Los cambios crean una versión
          nueva con tu nombre.
        </p>
      </div>

      <ReturnsPolicyForm tenantId={tenantId} />
    </div>
  )
}
