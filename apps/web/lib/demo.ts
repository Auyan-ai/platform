import type { components } from '@auyan/shared/api-types'

type TenantResponse = components['schemas']['TenantResponse']

export function isDemo(tenant: Pick<TenantResponse, 'origin'>): boolean {
  return tenant.origin === 'demo'
}

/** Slug propuesto al convertir una demo: el nombre de la tienda sin acentos ni símbolos. */
export function suggestClientSlug(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50)
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
