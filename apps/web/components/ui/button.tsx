import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

// Sistema semántico de radius (DESIGN.md §6.1):
// - tappable directly (primary, secondary, outline, destructive) → rounded-full (pill)
// - utilitarios (ghost, link) → rounded-sm (6px)
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary:
          'rounded-full bg-accent text-foreground-on-accent hover:bg-accent-hover',
        secondary:
          'rounded-full bg-secondary text-secondary-foreground border border-border hover:bg-surface-muted hover:border-border-strong',
        ghost:
          'rounded-sm text-foreground-body hover:bg-surface-muted hover:text-foreground',
        outline:
          'rounded-full border border-border bg-surface text-foreground hover:bg-surface-muted hover:border-border-strong',
        destructive:
          'rounded-full bg-danger text-foreground-on-accent hover:bg-danger-700',
        link:
          'rounded-sm text-accent underline-offset-4 hover:underline px-0',
      },
      size: {
        sm: 'h-8 px-3 text-xs',
        default: 'h-9 px-4',
        lg: 'h-10 px-6',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size, className }))}
        {...props}
      />
    )
  },
)
Button.displayName = 'Button'

export { Button, buttonVariants }
