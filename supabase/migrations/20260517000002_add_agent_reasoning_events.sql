-- Sprint 8: Agent Reasoning UI
-- Tabla de eventos de razonamiento del agente por conversación.
-- Los nodos del grafo emiten eventos fire-and-forget que se persisten aquí
-- para mostrar en el dashboard qué pensó/hizo el agente.

CREATE TABLE agent_reasoning_events (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    conversation_id uuid NOT NULL REFERENCES conversations(id),
    phase           text NOT NULL,          -- 'supervisor' | 'decision' | 'response'
    event_type      text NOT NULL,          -- 'check' | 'tool_call' | 'tool_result' | 'choice'
    label           text NOT NULL,          -- texto legible: "Detect abuse", "shopify.get_order_by_email"
    detail          jsonb,                  -- args del tool call, resultado, etc.
    status          text NOT NULL DEFAULT 'done',  -- 'pending' | 'done' | 'error'
    seq             integer NOT NULL DEFAULT 0,    -- orden dentro de la conversación
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

-- RLS: cada tenant solo ve sus propios eventos
ALTER TABLE agent_reasoning_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "tenant_isolation" ON agent_reasoning_events
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- Índice principal: listar eventos de una conversación en orden
CREATE INDEX idx_reasoning_events_conv_seq
    ON agent_reasoning_events(conversation_id, seq)
    WHERE deleted_at IS NULL;

-- Función trigger para updated_at automático (set_updated_at vive en public)
CREATE TRIGGER trg_reasoning_events_updated_at
    BEFORE UPDATE ON agent_reasoning_events
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
