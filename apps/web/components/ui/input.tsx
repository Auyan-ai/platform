import * as React from 'react'
import { cn } from '@/lib/utils'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        ref={ref}
        type={type}
        className={cn(
          'flex h-9 w-full rounded-sm border border-border bg-surface px-3 py-1 text-sm text-foreground transition-colors',
          'placeholder:text-foreground-subtle',
          'hover:border-border-strong',
          'disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-surface-muted',
          'aria-invalid:border-danger aria-invalid:focus-visible:outline-danger',
          'file:border-0 file:bg-transparent file:text-sm file:font-medium',
          className,
        )}
        {...props}
      />
    )
  },
)
Input.displayName = 'Input'

export { Input }
