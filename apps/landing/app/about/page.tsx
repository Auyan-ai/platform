import { SimplePage } from '@/components/SiteShell'
import { createPageMetadata } from '@/lib/metadata'

export const metadata = createPageMetadata({
  title: 'About',
  description:
    'Auyan es un equipo externo de Agent Engineers que configura, prueba y mejora agentes IA para CX e-commerce.',
  path: '/about',
})

export default function AboutPage() {
  return (
    <SimplePage eyebrow="About" title="Auyan es un equipo externo de Agent Engineers.">
      <p>
        Trabajamos con e-commerce español SMB+ y mid-market low-end. El cliente mantiene su equipo
        CX para casos complejos; Auyan configura, prueba, mantiene y optimiza el agente IA.
      </p>
      <p>
        La apuesta es simple: menos trabajo repetitivo para soporte, más tiempo para criterio humano
        y un ciclo semanal de mejora que no depende de que el cliente aprenda prompts.
      </p>
    </SimplePage>
  )
}
