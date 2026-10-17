import { ReturnsPolicyForm } from '@/components/returns-policy/ReturnsPolicyForm'

interface Props {
  params: Promise<{ tenantId: string }>
}

export default async function ClientReturnsPage({ params }: Props) {
  const { tenantId } = await params

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">
          Operación
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Devoluciones y cambios</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Define tu política. El agente solo gestiona devoluciones y cambios dentro de estas reglas.
        </p>
      </div>

      <ReturnsPolicyForm tenantId={tenantId} />
    </div>
  )
}
