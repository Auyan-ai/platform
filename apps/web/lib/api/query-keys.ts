/**
 * Fábrica de query keys para TanStack Query.
 * Convención: [dominio, ...args]. Usar siempre estas constantes para invalidar/prefetch.
 */
export const queryKeys = {
  tenants: {
    me: () => ['tenants', 'me'] as const,
    config: () => ['tenants', 'me', 'config'] as const,
    adminList: () => ['tenants', 'admin', 'list'] as const,
    metrics: (tenantId: string) => ['tenants', tenantId, 'metrics'] as const,
    usage: (tenantId: string) => ['tenants', tenantId, 'usage'] as const,
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
  aops: {
    list: (tenantId: string, workspace?: string) =>
      ['aops', tenantId, workspace ?? 'production'] as const,
    detail: (tenantId: string, aopId: string) => ['aops', tenantId, aopId] as const,
  },
  reasoning: {
    events: (tenantId: string, conversationId: string) =>
      ['reasoning', tenantId, conversationId] as const,
  },
  proposals: {
    list: (tenantId: string, filters?: Record<string, unknown>) =>
      ['proposals', tenantId, filters] as const,
    detail: (tenantId: string, proposalId: string) =>
      ['proposals', tenantId, proposalId] as const,
    metrics: (tenantId: string) => ['proposals', tenantId, 'metrics'] as const,
  },
} as const
