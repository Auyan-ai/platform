/**
 * Fábrica de query keys para TanStack Query.
 * Convención: [dominio, ...args]. Usar siempre estas constantes para invalidar/prefetch.
 */
export const queryKeys = {
  tenants: {
    me: () => ['tenants', 'me'] as const,
    config: () => ['tenants', 'me', 'config'] as const,
    adminList: () => ['tenants', 'admin', 'list'] as const,
  },
  conversations: {
    list: (tenantId: string, filters?: Record<string, unknown>) =>
      ['conversations', tenantId, filters] as const,
    detail: (tenantId: string, conversationId: string) =>
      ['conversations', tenantId, conversationId] as const,
  },
  escalations: {
    list: (tenantId: string, filters?: Record<string, unknown>) =>
      ['escalations', tenantId, filters] as const,
  },
} as const
