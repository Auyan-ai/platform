/**
 * Header de un step del wizard: H1 + subtitle. Misma jerarquía en split y centered.
 */
export function WizardStepHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6">
      <h1 className="mb-2 text-xl font-semibold leading-tight tracking-tight text-foreground">
        {title}
      </h1>
      {subtitle && (
        <p className="text-sm leading-relaxed text-foreground-muted">{subtitle}</p>
      )}
    </div>
  )
}
