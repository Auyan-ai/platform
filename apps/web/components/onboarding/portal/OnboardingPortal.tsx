'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  useSaveTenantOnboarding,
  useSubmitTenantOnboarding,
  useTenantOnboarding,
  useTenantOnboardingChecklist,
} from '@/lib/api/hooks/tenant-context'
import { Skeleton } from '@/components/ui/skeleton'
import { PortalShell } from './PortalShell'
import { Step1Basics } from './steps/Step1Basics'
import { Step2Voice } from './steps/Step2Voice'
import { Step3Facts } from './steps/Step3Facts'
import { Step4Shopify } from './steps/Step4Shopify'
import { Step5Helpdesk } from './steps/Step5Helpdesk'
import { Step6Kb } from './steps/Step6Kb'
import { Step7Legal } from './steps/Step7Legal'
import { Step8Call } from './steps/Step8Call'
import { Step9Confirm } from './steps/Step9Confirm'
import type { StepValues } from './steps/types'

const TOTAL_STEPS = 9

type StepData = Record<string, StepValues>

function normalizeStepData(data: Record<string, unknown>): StepData {
  return Object.fromEntries(
    Object.entries(data).map(([key, value]) => [
      key,
      value && typeof value === 'object' && !Array.isArray(value) ? (value as StepValues) : {},
    ]),
  )
}

interface OnboardingPortalProps {
  tenantId: string
  userEmail: string
  dashboardUrl: string
}

export function OnboardingPortal({ tenantId, userEmail, dashboardUrl }: OnboardingPortalProps) {
  const router = useRouter()
  const { data: onboarding, isLoading } = useTenantOnboarding(tenantId)
  const checklistQuery = useTenantOnboardingChecklist(tenantId)
  const saveMutation = useSaveTenantOnboarding(tenantId)
  const submitMutation = useSubmitTenantOnboarding(tenantId)

  const [step, setStep] = useState(1)
  const [stepData, setStepData] = useState<StepData>({})
  const [showWelcomeBack, setShowWelcomeBack] = useState(false)
  const initialized = useRef(false)

  // Resume-where-left-off: cuando llega el onboarding del server, arranca en current_step.
  useEffect(() => {
    if (!onboarding || initialized.current) return
    initialized.current = true
    setStep(onboarding.current_step)
    setStepData(normalizeStepData(onboarding.step_data))
    if (onboarding.current_step > 1 && !onboarding.submitted_at) {
      setShowWelcomeBack(true)
    }
  }, [onboarding])

  // Si el lifecycle ya pasó a building, sacamos al dashboard.
  useEffect(() => {
    const lifecycle = checklistQuery.data?.agent_lifecycle_state
    if (lifecycle && lifecycle !== 'initial' && lifecycle !== 'discovery') {
      router.replace(dashboardUrl)
    }
  }, [checklistQuery.data?.agent_lifecycle_state, dashboardUrl, router])

  const completedSteps = useMemo(() => {
    const completed = new Set<number>(onboarding?.completed_steps ?? [])
    for (let i = 1; i < step; i++) completed.add(i)
    const checklist = checklistQuery.data
    if (checklist?.has_commerce_integration) completed.add(4)
    if (checklist?.has_helpdesk_integration) completed.add(5)
    if (checklist?.has_knowledge) completed.add(6)
    return [...completed].sort((a, b) => a - b)
  }, [onboarding?.completed_steps, step, checklistQuery.data])

  const values = stepData[String(step)] ?? {}

  function handleChange(key: string, value: string | boolean | string[]) {
    setStepData((current) => ({
      ...current,
      [String(step)]: {
        ...(current[String(step)] ?? {}),
        [key]: value,
      },
    }))
  }

  async function persist(targetStep: number, nextData: StepData) {
    const nextCompleted = [...new Set([...completedSteps, step])].sort((a, b) => a - b)
    try {
      await saveMutation.mutateAsync({
        current_step: targetStep,
        completed_steps: nextCompleted,
        step_data: nextData,
      })
    } catch {
      // Silenciamos errores de save intermedios — el usuario puede continuar y el server reintenta
      // al próximo paso. Errores fatales aparecerían en el submit final.
    }
  }

  async function handleContinue() {
    const next = Math.min(TOTAL_STEPS, step + 1)
    setShowWelcomeBack(false)
    await persist(next, stepData)
    setStep(next)
  }

  function handleBack() {
    setStep((current) => Math.max(1, current - 1))
  }

  async function handleSubmit() {
    await persist(TOTAL_STEPS, stepData)
    await submitMutation.mutateAsync()
    // Tras submit, el server reevalúa lifecycle. Si pasa a building, el useEffect de arriba
    // redirige al dashboard. Si no, queda en discovery con el banner del checklist.
    router.replace(dashboardUrl)
  }

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Skeleton className="h-[400px] w-[440px]" />
      </div>
    )
  }

  const stepProps = {
    values,
    onChange: handleChange,
    onContinue: handleContinue,
    onBack: handleBack,
    onSkip: handleContinue,
    tenantId,
  }

  return (
    <PortalShell
      totalSteps={TOTAL_STEPS}
      currentStep={step}
      completedSteps={completedSteps}
      userEmail={userEmail}
    >
      {showWelcomeBack && (
        <div className="mx-auto mt-2 max-w-[640px] px-8">
          <div className="rounded-md border border-accent-subtle bg-accent-subtle px-4 py-2.5 text-sm text-accent-foreground">
            ↩ Bienvenido de vuelta. Continuamos donde lo dejaste: paso {step} de {TOTAL_STEPS}.
          </div>
        </div>
      )}
      {step === 1 && <Step1Basics {...stepProps} />}
      {step === 2 && <Step2Voice {...stepProps} />}
      {step === 3 && <Step3Facts {...stepProps} />}
      {step === 4 && <Step4Shopify {...stepProps} />}
      {step === 5 && <Step5Helpdesk {...stepProps} />}
      {step === 6 && <Step6Kb {...stepProps} />}
      {step === 7 && <Step7Legal {...stepProps} />}
      {step === 8 && <Step8Call {...stepProps} />}
      {step === 9 && <Step9Confirm {...stepProps} onContinue={handleSubmit} />}
    </PortalShell>
  )
}
