import * as React from 'react'
import { cn } from '@/lib/utils'

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={cn(
          'flex min-h-[80px] w-full rounded-sm border border-border bg-surface px-3 py-2 text-sm text-foreground transition-colors',
          'placeholder:text-foreground-subtle',
          'hover:border-border-strong',
          'disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-surface-muted',
          'aria-invalid:border-danger',
          className,
        )}
        {...props}
      />
    )
  },
)
Textarea.displayName = 'Textarea'

export { Textarea }
