'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getToken } from '@/lib/api/get-token'
import { queryKeys } from '@/lib/api/query-keys'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// ─── Types ────────────────────────────────────────────────────────────────────

export type SimulationStatus = 'running' | 'passed' | 'partial' | 'failed' | 'errored'
export type TerminationReason =
  | 'goal_achieved'
  | 'max_turns'
  | 'give_up'
  | 'escalated_by_agent'
  | 'agent_loop_detected'
  | 'error'

export interface SimulationScenario {
  id: string
  tenant_id: string
  name: string
  description: string | null
  aop_slug: string
  user_profile_id: string
  expected_outcome: string
  mock_fixtures: Record<string, unknown>
  assertions: Record<string, unknown>
  max_turns: number
  is_active: boolean
}

export interface TranscriptTurn {
  role: 'customer' | 'agent'
  content: string
  turn_number: number
  goal_achieved: boolean
  give_up: boolean
  internal_reasoning: string
  tokens_in: number
  tokens_out: number
}

export interface JudgeEval {
  reasoning_score: number
  knowledge_score: number
  tools_score: number
  brand_voice_score: number
  overall_score: number
  verdict: 'pass' | 'partial' | 'fail'
  reasoning_explanation: string
  knowledge_explanation: string
  tools_explanation: string
  brand_voice_explanation: string
  judge_goal_achieved: boolean
  judge_goal_explanation: string
  suggestions: string
  model_used: string
  input_tokens: number
  output_tokens: number
}

export interface AssertionResult {
  key: string
  passed: boolean
  evidence: string
  is_critical: boolean
}

export interface SimulationRun {
  id: string
  tenant_id: string
  scenario_id: string | null
  aop_slug: string
  status: SimulationStatus
  termination_reason: TerminationReason | null
  turns_count: number | null
  transcript: TranscriptTurn[] | null
  judge_eval: JudgeEval | null
  assertions_results: AssertionResult[] | null
  assertions_passed: number | null
  assertions_total: number | null
  tokens_simulator: number
  tokens_agent: number
  tokens_judge: number
  cost_cents: number | null
  started_at: string | null
  completed_at: string | null
}

export interface BatchCreated {
  batch_id: string
  scenario_count: number
}

// ─── Helper ───────────────────────────────────────────────────────────────────

async function simFetch<T>(
  token: string,
  tenantId: string,
  path: string,
  options?: RequestInit,
): Promise<T> {
  const resp = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      'X-Tenant-Id': tenantId,
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail ?? `HTTP ${resp.status}`)
  }
  return resp.json() as Promise<T>
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useSimulationScenarios(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.simulations.scenarios(tenantId),
    queryFn: async () => {
      const token = await getToken()
      return simFetch<SimulationScenario[]>(token, tenantId, '/simulations/scenarios')
    },
    staleTime: 30_000,
  })
}

export function useScenarioRuns(tenantId: string, scenarioId: string) {
  return useQuery({
    queryKey: queryKeys.simulations.scenarioRuns(tenantId, scenarioId),
    queryFn: async () => {
      const token = await getToken()
      return simFetch<SimulationRun[]>(
        token,
        tenantId,
        `/simulations/scenarios/${scenarioId}/runs`,
      )
    },
    staleTime: 10_000,
    refetchInterval: 10_000,
  })
}

export function useSimulationRun(tenantId: string, runId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.simulations.run(tenantId, runId),
    queryFn: async () => {
      const token = await getToken()
      return simFetch<SimulationRun>(token, tenantId, `/simulations/runs/${runId}`)
    },
    enabled,
    staleTime: 5_000,
  })
}

export function useBatchRuns(tenantId: string, batchId: string | null) {
  return useQuery({
    queryKey: queryKeys.simulations.batch(tenantId, batchId ?? ''),
    queryFn: async () => {
      const token = await getToken()
      return simFetch<SimulationRun[]>(token, tenantId, `/simulations/batches/${batchId}`)
    },
    enabled: Boolean(batchId),
    refetchInterval: (query) => {
      const runs = query.state.data
      if (!runs) return 3_000
      const allDone = runs.every((r) => r.status !== 'running')
      return allDone ? false : 3_000
    },
  })
}

export function useRunSimulation(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (scenarioId: string) => {
      const token = await getToken()
      return simFetch<SimulationRun>(token, tenantId, '/simulations/runs', {
        method: 'POST',
        body: JSON.stringify({ scenario_id: scenarioId }),
      })
    },
    onSuccess: (_data, scenarioId) => {
      qc.invalidateQueries({
        queryKey: queryKeys.simulations.scenarioRuns(tenantId, scenarioId),
      })
    },
  })
}

export function useRunBatch(tenantId: string) {
  return useMutation({
    mutationFn: async (scenarioIds: string[]) => {
      const token = await getToken()
      return simFetch<BatchCreated>(token, tenantId, '/simulations/batches', {
        method: 'POST',
        body: JSON.stringify({ scenario_ids: scenarioIds }),
      })
    },
  })
}
