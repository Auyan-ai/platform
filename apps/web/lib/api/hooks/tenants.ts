'use client'

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { components } from '@auyan/shared/api-types'

type TenantResponse = components['schemas']['TenantResponse']

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
      const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
      const res = await fetch(`${baseUrl}/tenants/admin/list`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(`Error ${res.status} al listar tenants`)
      return res.json() as Promise<TenantResponse[]>
    },
    staleTime: 60_000,
  })
}
