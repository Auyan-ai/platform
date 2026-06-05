"""Schemas para el tool output de Claude.

Doble representación:
- `RESPOND_OR_ESCALATE_TOOL`: JSON Schema enviado a la API de Anthropic.
- `AgentDecisionTool`: Pydantic model que valida lo que devuelve el LLM.

Mantenerlos sincronizados.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ----------------------------------------------------------------
# JSON Schema para la herramienta (lo que ve Claude)
# ----------------------------------------------------------------

RESPOND_OR_ESCALATE_TOOL: dict[str, Any] = {
    "name": "respond_or_escalate",
    "description": (
        "Decide cómo manejar el mensaje del cliente: responder directamente o escalar "
        "a un agente humano. SIEMPRE usa esta herramienta — no contestes en texto plano."
    ),
    "input_schema": {
        "type": "object",
        "required": ["decision", "confidence", "response_text"],
        "additionalProperties": False,
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["respond", "escalate"],
                "description": (
                    "'respond' = el agente AI responde al cliente. "
                    "'escalate' = se pasa a un agente humano."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Tu confianza en esta decisión, en [0,1]. Si dudas o el contexto es "
                    "insuficiente, pon un valor bajo y considera escalar."
                ),
            },
            "response_text": {
                "type": "string",
                "description": (
                    "Mensaje visible para el cliente. OBLIGATORIO siempre. "
                    "Si decision='respond' → la respuesta. "
                    "Si decision='escalate' → mensaje de cortesía explicando que se "
                    "pasa con un agente humano (NUNCA dejar al cliente sin respuesta). "
                    "Tono profesional, breve, en el idioma del cliente. No inventes información."
                ),
            },
            "escalation_reason": {
                "type": "string",
                "description": (
                    "Razón interna del escalado (NO visible para el cliente). "
                    "OBLIGATORIO cuando decision='escalate'. "
                    "Ejemplos: 'customer_requested_human', 'out_of_scope_refund_policy', "
                    "'insufficient_context_in_knowledge_base'."
                ),
            },
            "awaiting_customer_reply": {
                "type": "boolean",
                "description": (
                    "true SOLO si tu response_text le pide al cliente más información o "
                    "una aclaración para poder continuar (p.ej. pedirle el nº de pedido, "
                    "preguntarle qué artículo, confirmar una dirección). false si tu "
                    "respuesta resuelve o cierra la consulta. Por defecto false. "
                    "Se usa para no cerrar el ticket cuando aún esperas al cliente."
                ),
            },
        },
    },
}


# ----------------------------------------------------------------
# Pydantic — validación del tool output del LLM
# ----------------------------------------------------------------


class AgentDecisionTool(BaseModel):
    """Validación estricta de lo que Claude devuelve por el tool use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["respond", "escalate"]
    confidence: float = Field(ge=0.0, le=1.0)
    response_text: str
    escalation_reason: str | None = None
    awaiting_customer_reply: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> AgentDecisionTool:
        if not self.response_text.strip():
            raise ValueError(
                "response_text es obligatorio y no vacío para cualquier decision"
            )
        if self.decision == "escalate":
            if not self.escalation_reason or not self.escalation_reason.strip():
                raise ValueError(
                    "escalation_reason es obligatorio y no vacío cuando decision='escalate'"
                )
        return self
