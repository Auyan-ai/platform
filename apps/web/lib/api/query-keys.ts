/**
 * Fábrica de query keys para TanStack Query.
 * Convención: [dominio, ...args]. Usar siempre estas constantes para invalidar/prefetch.
 */
export const queryKeys = {
  tenants: {
    me: () => ['tenants', 'me'] as const,
    config: () => ['tenants', 'me', 'config'] as const,
    adminList: () => ['tenants', 'admin', 'list'] as const,
    adminReviewQueue: () => ['tenants', 'admin', 'review-queue'] as const,
    metrics: (tenantId: string) => ['tenants', tenantId, 'metrics'] as const,
    insights: (tenantId: string, days?: number) =>
      ['tenants', tenantId, 'insights', days ?? 14] as const,
    usage: (tenantId: string, days?: number) => ['tenants', tenantId, 'usage', days ?? 7] as const,
    playbook: (tenantId: string) => ['tenants', tenantId, 'playbook'] as const,
    facts: (tenantId: string) => ['tenants', tenantId, 'facts'] as const,
    onboarding: (tenantId: string) => ['tenants', tenantId, 'onboarding'] as const,
    onboardingChecklist: (tenantId: string) =>
      ['tenants', tenantId, 'onboarding', 'checklist'] as const,
    integrations: (tenantId: string) => ['tenants', tenantId, 'integrations'] as const,
    kbSubmissions: (tenantId: string, status?: string) =>
      ['tenants', tenantId, 'kb-submissions', status ?? 'all'] as const,
    weeklyReports: (tenantId: string, status?: string) =>
      ['tenants', tenantId, 'weekly-reports', status ?? 'all'] as const,
    outboundEmailTemplates: (tenantId: string) =>
      ['tenants', tenantId, 'outbound-email', 'templates'] as const,
    outboundEmailJobs: (tenantId: string, status?: string) =>
      ['tenants', tenantId, 'outbound-email', 'jobs', status ?? 'all'] as const,
  },
  conversations: {
    list: (tenantId: string, filters?: Record<string, unknown>) =>
      ['conversations', tenantId, filters] as const,
    detail: (tenantId: string, conversationId: string) =>
      ['conversations', tenantId, conversationId] as const,
    attachment: (tenantId: string, messageId: string, index: number) =>
      ['conversations', tenantId, 'attachment', messageId, index] as const,
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
    detail: (tenantId: string, proposalId: string) => ['proposals', tenantId, proposalId] as const,
    metrics: (tenantId: string) => ['proposals', tenantId, 'metrics'] as const,
  },
  simulations: {
    scenarios: (tenantId: string) => ['simulations', tenantId, 'scenarios'] as const,
    scenarioRuns: (tenantId: string, scenarioId: string) =>
      ['simulations', tenantId, 'scenarios', scenarioId, 'runs'] as const,
    run: (tenantId: string, runId: string) => ['simulations', tenantId, 'runs', runId] as const,
    batch: (tenantId: string, batchId: string) =>
      ['simulations', tenantId, 'batches', batchId] as const,
  },
} as const
