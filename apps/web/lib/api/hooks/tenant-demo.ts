'use client'

import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'
import type { components } from '@auyan/shared/api-types'
import { useMutation, useQueryClient } from '@tanstack/react-query'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type TenantResponse = components['schemas']['TenantResponse']

export function useCreateDemo() {
  const qc = useQueryClient()
  return useMutation<TenantResponse, Error, { url: string }>({
    mutationFn: async ({ url }) => {
      const token = await getToken()
      const resp = await fetch(`${API_URL}/tenants/demos`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url }),
      })
      if (!resp.ok) {
        let detail = `Error ${resp.status}`
        try {
          const body = (await resp.json()) as { detail?: string }
          if (typeof body.detail === 'string') detail = body.detail
        } catch {
          // ignore json parse error
        }
        throw new Error(detail)
      }
      return (await resp.json()) as TenantResponse
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tenants.adminList() })
    },
  })
}
