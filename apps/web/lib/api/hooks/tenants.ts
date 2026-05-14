'use client'

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

export function useMyTenant() {
  return useQuery({
    queryKey: queryKeys.tenants.me(),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token).GET('/tenants/me')
      if (error) throw error
      return data
    },
  })
}

export function useMyTenantConfig() {
  return useQuery({
    queryKey: queryKeys.tenants.config(),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token).GET('/tenants/me/config')
      if (error) throw error
      return data
    },
  })
}
