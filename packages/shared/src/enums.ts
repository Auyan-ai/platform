// Espejo exacto de los Literal types de apps/api/db/models.py
// Fuente única — al cambiar el Python, actualizar acá también.

export type MessageRole = 'customer' | 'agent_ai' | 'agent_human' | 'system'
export type MessageDirection = 'inbound' | 'outbound'
export type ConversationStatus =
  | 'open'
  | 'pending'
  | 'resolved'
  | 'escalated'
  | 'closed'
  | 'closed_abandoned'
export type EscalationStatus = 'pending' | 'claimed' | 'resolved'
export type ChannelType =
  | 'email'
  | 'chat'
  | 'widget'
  | 'whatsapp'
  | 'instagram'
  | 'zendesk'
  | 'intercom'
  | 'chatwoot'
export type UserRole = 'super_admin' | 'tenant_admin'
