import type { ReactNode } from 'react'
import Image from 'next/image'

/**
 * Layout split 50/50 — formulario izquierda, imagen atmosférica derecha.
 * Para steps de "acción": Shopify, Helpdesk, KB, AIDE call.
 */
export function WizardSplitLayout({
  children,
  imageSrc,
  imageAlt,
}: {
  children: ReactNode
  imageSrc?: string
  imageAlt?: string
}) {
  return (
    <div className="grid flex-1 grid-cols-1 lg:grid-cols-2">
      <div className="flex flex-col items-center justify-center px-8 py-8 lg:px-16">
        <div className="w-full max-w-[420px]">{children}</div>
      </div>
      <div className="relative hidden border-l border-border bg-surface-muted lg:block">
        {imageSrc ? (
          <Image
            src={imageSrc}
            alt={imageAlt ?? ''}
            fill
            sizes="50vw"
            className="object-cover"
            priority
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center p-12">
            <div className="max-w-[320px] rounded-md border border-dashed border-border-strong p-6 text-center font-mono text-xs text-foreground-subtle">
              <strong className="mb-2 block font-sans text-sm font-medium text-foreground-muted">
                [Imagen pendiente]
              </strong>
              Captura atmosférica blurred KREA del contexto del step.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Layout centrado, single column — para steps puramente de input/confirmación.
 * Step 1 (Datos básicos), Step 7 (Legal), Step 9 (Confirmación).
 */
export function WizardCenteredLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-8">
      <div className="w-full max-w-[440px]">{children}</div>
    </div>
  )
}
