'use client'

import { useQuery } from '@tanstack/react-query'
import { createClient } from '@/lib/supabase/client'
import { apiClient } from '@/lib/api/client'
import { queryKeys } from '@/lib/api/query-keys'

async function getToken(): Promise<string> {
  const supabase = createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()
  if (!session?.access_token) throw new Error('Sin sesión activa')
  return session.access_token
}

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
