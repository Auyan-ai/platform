import { SimplePage } from '@/components/SiteShell'

const tiers = [
  ['Starter', '€890/mes', '1.000 tickets/mes', 'Para equipos CX de 2-4 personas.'],
  ['Growth', '€2.490/mes', '3.000 tickets/mes', 'Target principal SMB+ y mid-market low-end.'],
  ['Scale', '€5.990/mes', '10.000 tickets/mes', 'Para operaciones con 10-25 personas CX.'],
] as const

export default function PricingPage() {
  return (
    <SimplePage eyebrow="Pricing" title="Planes ligados a operación, no asientos.">
      <p>
        Primeros clientes: Founding Partner con setup gratis, mes 1 gratis y meses 2-6 a €690/mes.
      </p>
      <div className="grid gap-4 pt-2 md:grid-cols-3">
        {tiers.map(([name, price, tickets, note]) => (
          <div key={name} className="rounded-md border border-border bg-surface p-5">
            <h2 className="text-xl font-semibold text-foreground">{name}</h2>
            <p className="mt-4 text-2xl font-semibold text-foreground">{price}</p>
            <p className="mt-2 text-sm text-accent-foreground">{tickets}</p>
            <p className="mt-4 text-sm leading-6 text-foreground-muted">{note}</p>
          </div>
        ))}
      </div>
    </SimplePage>
  )
}
