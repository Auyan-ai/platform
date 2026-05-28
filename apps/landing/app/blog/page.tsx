import { SimplePage } from '@/components/SiteShell'

const posts = [
  ['Por qué Managed AI no es otro chatbot', 'Modelo operativo para CX e-commerce.'],
  ['Shadow mode en semana 3', 'Cómo aprender del equipo CX sin poner clientes en riesgo.'],
  ['El reporte semanal como producto', 'El cliente recibe decisiones, no dashboards vacíos.'],
] as const

export default function BlogPage() {
  return (
    <SimplePage eyebrow="Blog" title="Notas desde la operación.">
      <div className="grid gap-4">
        {posts.map(([title, description]) => (
          <article key={title} className="rounded-md border border-border bg-surface p-5">
            <h2 className="text-xl font-semibold text-foreground">{title}</h2>
            <p className="mt-2 text-base text-foreground-muted">{description}</p>
          </article>
        ))}
      </div>
    </SimplePage>
  )
}
