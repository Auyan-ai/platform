'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * Input estilo Linear-light para el onboarding portal.
 * Sin border visible, bg sutil más cálido que la página, focus → bg-white + ring cobalto.
 * NO reemplaza Input.tsx del dashboard (que usa border visible Mercury-style).
 */
export interface WizardInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
}

export const WizardInput = React.forwardRef<HTMLInputElement, WizardInputProps>(
  ({ className, label, id, ...props }, ref) => {
    const inputId = id ?? React.useId()
    return (
      <div>
        {label && (
          <label
            htmlFor={inputId}
            className="mb-1.5 block text-xs font-normal text-foreground-muted"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            'flex h-9 w-full rounded-sm border border-transparent bg-surface-muted px-3 text-sm text-foreground transition-colors',
            'placeholder:text-foreground-subtle',
            'hover:bg-[#EEECEA]',
            'focus:bg-surface focus:border-accent focus:outline-2 focus:outline-accent focus:outline-offset-2 focus:outline',
            'disabled:cursor-not-allowed disabled:opacity-50',
            className,
          )}
          {...props}
        />
      </div>
    )
  },
)
WizardInput.displayName = 'WizardInput'
