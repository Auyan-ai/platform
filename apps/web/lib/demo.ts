import type { components } from '@auyan/shared/api-types'

type TenantResponse = components['schemas']['TenantResponse']

export function isDemo(tenant: Pick<TenantResponse, 'origin'>): boolean {
  return tenant.origin === 'demo'
}

const DATE_FORMAT = new Intl.DateTimeFormat('es-ES', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

export function demoBadgeLabel(expiresAt: string | null | undefined): string {
  if (!expiresAt) return 'Demo'
  return `Demo · caduca ${DATE_FORMAT.format(new Date(expiresAt))}`
}
