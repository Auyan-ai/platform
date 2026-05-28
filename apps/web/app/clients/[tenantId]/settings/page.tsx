import { ClientSettingsPanel } from '@/components/settings/ClientSettingsPanel'

export default async function ClientSettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-foreground-muted">Cuenta</p>
        <h1 className="mt-1 text-2xl font-semibold text-foreground">Configuración</h1>
        <p className="mt-1 max-w-2xl text-sm text-foreground-muted">
          Integraciones conectadas, branding operativo y contacto AIDE asignado.
        </p>
      </div>

      <ClientSettingsPanel />
    </div>
  )
}
