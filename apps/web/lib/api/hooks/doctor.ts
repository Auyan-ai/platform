'use client'

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { components } from '@auyan/shared/api-types'

export type DoctorReport = components['schemas']['DoctorReport']
export type DoctorCheck = components['schemas']['DoctorCheck']
export type DoctorStatus = DoctorCheck['status']

/** Doctor del tenant (solo super_admin). Llama a APIs de terceros: tarda unos segundos. */
export function useTenantDoctor(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.tenants.doctor(tenantId),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token, tenantId).GET('/tenants/me/doctor')
      if (error) {
        const detail = (error as { detail?: unknown }).detail
        throw new Error(typeof detail === 'string' ? detail : 'No se pudo correr el doctor')
      }
      return data as DoctorReport
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  })
}
