'use client'

import { apiClient } from '@/lib/api/client'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { components } from '@auyan/shared/api-types'
import { useQuery } from '@tanstack/react-query'

type TenantResponse = components['schemas']['TenantResponse']
type AdminReviewQueueItem = components['schemas']['AdminReviewQueueItem']

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

export function useAdminTenants() {
  return useQuery({
    queryKey: queryKeys.tenants.adminList(),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token).GET('/tenants/admin/list')
      if (error) throw error
      return data as TenantResponse[]
    },
    staleTime: 60_000,
  })
}

export function useAdminReviewQueue() {
  return useQuery({
    queryKey: queryKeys.tenants.adminReviewQueue(),
    queryFn: async () => {
      const token = await getToken()
      const { data, error } = await apiClient(token).GET('/tenants/admin/review-queue')
      if (error) throw error
      return data as AdminReviewQueueItem[]
    },
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}
