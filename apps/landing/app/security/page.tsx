import { SimplePage } from '@/components/SiteShell'

export default function SecurityPage() {
  return (
    <SimplePage eyebrow="Security" title="Diseñado para operar sobre tu stack, con límites claros.">
      <p>
        Auyan hereda canales del helpdesk del cliente. No construimos un canal paralelo ni movemos
        credenciales al dashboard cliente. Las acciones sensibles pasan por permisos L3 y colas de
        aprobación.
      </p>
      <p>
        El dashboard separa operación interna de vista cliente. Las conversaciones en cliente usan
        lectura controlada y el equipo Auyan mantiene los cambios de playbook, KB y AOPs.
      </p>
    </SimplePage>
  )
}
