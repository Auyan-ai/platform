import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle,
  BookOpenText,
  CheckCircle2,
  FileBarChart2,
  FileText,
  FlaskConical,
  Mail,
  MessageCircleQuestion,
  MessagesSquare,
  ScrollText,
  Sparkles,
  Stethoscope,
  Undo2,
} from 'lucide-react'

export type TenantSection =
  | 'conversations'
  | 'escalations'
  | 'approvals'
  | 'playbook'
  | 'returns'
  | 'knowledge'
  | 'reports'
  | 'emails'
  | 'aops'
  | 'proposals'
  | 'simulator'
  | 'probar-agente'
  | 'doctor'

export interface TenantNavItem {
  label: string
  icon: LucideIcon
  section: TenantSection
  keywords: string[]
}

export interface TenantNavGroup {
  label: string
  items: TenantNavItem[]
}

export const DEFAULT_TENANT_SECTION: TenantSection = 'conversations'

export const TENANT_NAV_GROUPS: TenantNavGroup[] = [
  {
    label: 'Atención',
    items: [
      {
        label: 'Conversaciones',
        icon: MessagesSquare,
        section: 'conversations',
        keywords: ['inbox', 'chats', 'mensajes'],
      },
      {
        label: 'Escalaciones',
        icon: AlertTriangle,
        section: 'escalations',
        keywords: ['alertas', 'soporte', 'handoff'],
      },
      {
        label: 'Aprobaciones',
        icon: CheckCircle2,
        section: 'approvals',
        keywords: ['pendientes', 'acciones', 'reviews'],
      },
    ],
  },
  {
    label: 'Conocimiento',
    items: [
      {
        label: 'Playbook',
        icon: BookOpenText,
        section: 'playbook',
        keywords: ['marca', 'voz', 'reglas'],
      },
      {
        label: 'Devoluciones y cambios',
        icon: Undo2,
        section: 'returns',
        keywords: ['devoluciones', 'cambios', 'politica', 'plazo', 'reembolso', 'returns'],
      },
      {
        label: 'KB Review',
        icon: FileText,
        section: 'knowledge',
        keywords: ['knowledge', 'base', 'documentos'],
      },
      {
        label: 'Reportes',
        icon: FileBarChart2,
        section: 'reports',
        keywords: ['weekly', 'informes', 'metricas'],
      },
      {
        label: 'Emails',
        icon: Mail,
        section: 'emails',
        keywords: ['outbound', 'plantillas', 'correo'],
      },
    ],
  },
  {
    label: 'Automatización',
    items: [
      {
        label: 'AOPs',
        icon: ScrollText,
        section: 'aops',
        keywords: ['procedimientos', 'operaciones', 'workflows'],
      },
      {
        label: 'Mejoras propuestas',
        icon: Sparkles,
        section: 'proposals',
        keywords: ['mejoras', 'propuestas', 'revisar'],
      },
      {
        label: 'Simulador',
        icon: FlaskConical,
        section: 'simulator',
        keywords: ['simulator', 'pruebas', 'tests'],
      },
      {
        label: 'Probar agente',
        icon: MessageCircleQuestion,
        section: 'probar-agente',
        keywords: ['chat', 'demo', 'probar', 'batería'],
      },
    ],
  },
  {
    label: 'Operación',
    items: [
      {
        label: 'Diagnóstico',
        icon: Stethoscope,
        section: 'doctor',
        keywords: ['doctor', 'salud', 'integraciones', 'webhooks', 'triggers', 'migraciones'],
      },
    ],
  },
]

export const TENANT_NAV_ITEMS = TENANT_NAV_GROUPS.flatMap((group) => group.items)

export function getTenantSectionFromPath(pathname: string): TenantSection {
  const section = pathname.match(/\/tenants\/[^/]+\/([^/]+)/)?.[1]
  const match = TENANT_NAV_ITEMS.find((item) => item.section === section)
  return match?.section ?? DEFAULT_TENANT_SECTION
}
