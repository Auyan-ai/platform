"""4 arquetipos de persona del cliente sintético.

Se usan para construir UserProfile rows cuando se hace seed a un tenant.
El campo `persona` se almacena como JSONB en `user_profiles.persona`.
"""

from __future__ import annotations

PERSONAS: dict[str, dict] = {
    "cooperativo": {
        "tone": "amable y directo",
        "behavior": (
            "Das información cuando te la piden. Eres paciente. "
            "Aceptas explicaciones razonables sin presionar."
        ),
        "give_up_after": 10,
    },
    "impaciente": {
        "tone": "frustrado, mensajes cortos",
        "behavior": (
            "Si no hay solución en 2 turnos del agente, presionas con frustración. "
            "No elaboras mucho. Usas frases cortas."
        ),
        "give_up_after": 3,
    },
    "vago": {
        "tone": "confundido, información mínima",
        "behavior": (
            "No das número de pedido a menos que el agente lo pida explícitamente. "
            "Respondes con la mínima información posible."
        ),
        "give_up_after": 8,
    },
    "abandona_pronto": {
        "tone": "desinteresado, pasivo",
        "behavior": (
            "Si no hay respuesta clara en 2 turnos del agente, desistes sin escalar. "
            "No insistes ni presionas."
        ),
        "give_up_after": 2,
    },
}
