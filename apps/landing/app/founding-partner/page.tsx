import { SimplePage } from '@/components/SiteShell'

export default function FoundingPartnerPage() {
  return (
    <SimplePage eyebrow="Founding Partner" title="Primeros cinco clientes, con feedback semanal.">
      <p>
        Setup gratis, mes 1 gratis, meses 2-6 a €690/mes y sin permanencia. A cambio pedimos
        feedback semanal, una llamada de 30 minutos y permiso para construir un caso de estudio
        público cuando haya resultados.
      </p>
      <p>
        El mejor inicio es el killer test: tres emails reales anonimizados del último mes. En 24h
        comparamos cómo respondería Auyan contra la respuesta de tu equipo.
      </p>
      <a
        href="mailto:founders@auyan.ai?subject=Founding%20Partner%20Auyan"
        className="inline-flex h-11 items-center rounded-sm bg-accent px-5 text-sm font-medium text-foreground-on-accent"
      >
        Escribir a Auyan
      </a>
    </SimplePage>
  )
}
