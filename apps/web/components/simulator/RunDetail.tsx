'use client'

import { cn } from '@/lib/utils'
import type { AssertionResult, JudgeEval, SimulationRun, TranscriptTurn } from '@/lib/api/hooks/simulations'

// ─── Transcript ───────────────────────────────────────────────────────────────

function TranscriptView({ turns }: { turns: TranscriptTurn[] }) {
  return (
    <div className="space-y-2">
      {turns.map((turn) => (
        <div
          key={turn.turn_number}
          className={cn('flex', turn.role === 'agent' ? 'justify-start' : 'justify-end')}
        >
          <div
            className={cn(
              'max-w-[80%] rounded-2xl px-3 py-2 text-sm',
              turn.role === 'agent'
                ? 'bg-neutral-100 text-neutral-800 rounded-tl-sm'
                : 'bg-blue-600 text-white rounded-tr-sm',
            )}
          >
            <p className="text-xs font-medium mb-1 opacity-60">
              {turn.role === 'agent' ? 'Agente' : 'Cliente'} · T{turn.turn_number}
            </p>
            <p className="whitespace-pre-wrap leading-relaxed">{turn.content}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Judge Scores ─────────────────────────────────────────────────────────────

const SCORE_DIMS: { key: keyof JudgeEval; label: string; explKey: keyof JudgeEval }[] = [
  { key: 'reasoning_score', label: 'Razonamiento', explKey: 'reasoning_explanation' },
  { key: 'knowledge_score', label: 'Conocimiento', explKey: 'knowledge_explanation' },
  { key: 'tools_score', label: 'Tools', explKey: 'tools_explanation' },
  { key: 'brand_voice_score', label: 'Brand voice', explKey: 'brand_voice_explanation' },
]

function ScoreBar({ score }: { score: number }) {
  const pct = (score / 10) * 100
  const color =
    score >= 7.5 ? 'bg-emerald-500' : score >= 6 ? 'bg-amber-400' : 'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-neutral-100 rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular-nums text-xs font-medium w-6 text-right">{score}</span>
    </div>
  )
}

function JudgeScores({ judge }: { judge: JudgeEval }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-neutral-500 uppercase tracking-wide">
          Evaluación del judge
        </span>
        <span className="text-sm font-semibold tabular-nums">
          {judge.overall_score.toFixed(1)}/10
        </span>
      </div>
      {SCORE_DIMS.map(({ key, label, explKey }) => (
        <div key={key}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-neutral-600">{label}</span>
          </div>
          <ScoreBar score={judge[key] as number} />
          <p className="mt-1 text-xs text-neutral-500 leading-snug">
            {judge[explKey] as string}
          </p>
        </div>
      ))}
      <div className="pt-2 border-t border-neutral-100">
        <p className="text-xs text-neutral-500 mb-1">
          <span className="font-medium">Goal logrado:</span>{' '}
          {judge.judge_goal_achieved ? 'Sí' : 'No'} — {judge.judge_goal_explanation}
        </p>
        {judge.suggestions && (
          <p className="text-xs text-neutral-500">
            <span className="font-medium">Sugerencias:</span> {judge.suggestions}
          </p>
        )}
      </div>
    </div>
  )
}

// ─── Assertions ───────────────────────────────────────────────────────────────

function AssertionsTable({ results }: { results: AssertionResult[] }) {
  return (
    <div className="space-y-1.5">
      <span className="text-xs font-semibold text-neutral-500 uppercase tracking-wide">
        Assertions programáticas
      </span>
      {results.map((r) => (
        <div
          key={r.key}
          className="flex items-start gap-2 text-xs py-1 border-b border-neutral-50 last:border-0"
        >
          <span
            className={cn(
              'mt-0.5 shrink-0 rounded-full w-4 h-4 flex items-center justify-center text-[10px] font-bold',
              r.passed
                ? 'bg-emerald-100 text-emerald-700'
                : 'bg-red-100 text-red-600',
            )}
          >
            {r.passed ? '✓' : '✗'}
          </span>
          <div className="flex-1 min-w-0">
            <span className="font-mono text-neutral-700">{r.key}</span>
            {r.is_critical && (
              <span className="ml-1.5 text-[10px] font-semibold text-red-500 uppercase">
                crítica
              </span>
            )}
            {r.evidence && (
              <p className="text-neutral-400 mt-0.5 leading-snug">{r.evidence}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── RunDetail ────────────────────────────────────────────────────────────────

const TERMINATION_LABEL: Record<string, string> = {
  goal_achieved: 'Goal logrado',
  max_turns: 'Límite de turnos',
  give_up: 'Cliente abandonó',
  escalated_by_agent: 'Escalado por agente',
  agent_loop_detected: 'Loop detectado',
  error: 'Error',
}

interface RunDetailProps {
  run: SimulationRun
}

export function RunDetail({ run }: RunDetailProps) {
  const totalTokens = run.tokens_simulator + run.tokens_agent + run.tokens_judge
  const costUsd = run.cost_cents ? (run.cost_cents / 100).toFixed(4) : null

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-4">
      {/* Left: transcript */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-semibold text-neutral-500 uppercase tracking-wide">
            Transcript
          </span>
          <div className="flex items-center gap-3 text-xs text-neutral-400">
            {run.turns_count != null && <span>{run.turns_count} turnos</span>}
            {run.termination_reason && (
              <span>{TERMINATION_LABEL[run.termination_reason] ?? run.termination_reason}</span>
            )}
            {totalTokens > 0 && <span>{totalTokens.toLocaleString()} tok</span>}
            {costUsd && <span>${costUsd}</span>}
          </div>
        </div>
        {run.transcript?.length ? (
          <TranscriptView turns={run.transcript} />
        ) : (
          <p className="text-xs text-neutral-400 italic">Sin transcript disponible</p>
        )}
      </div>

      {/* Right: judge + assertions */}
      <div className="space-y-5">
        {run.judge_eval ? (
          <JudgeScores judge={run.judge_eval} />
        ) : (
          <p className="text-xs text-neutral-400 italic">Sin evaluación del judge</p>
        )}
        {run.assertions_results?.length ? (
          <AssertionsTable results={run.assertions_results} />
        ) : null}
      </div>
    </div>
  )
}
