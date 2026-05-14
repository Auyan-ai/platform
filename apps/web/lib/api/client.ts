import createClient from 'openapi-fetch'
import type { paths } from '@auyan/shared/api-types'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/**
 * Crea un cliente HTTP tipado contra el FastAPI.
 * Úsalo en RSC pasando el access_token de la sesión Supabase del server.
 * Úsalo en hooks de TanStack Query pasando el token leído de getSession().
 */
export function apiClient(token: string, tenantId?: string) {
  return createClient<paths>({
    baseUrl: API_URL,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(tenantId ? { 'X-Tenant-Id': tenantId } : {}),
    },
  })
}
