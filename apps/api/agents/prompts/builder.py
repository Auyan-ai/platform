"""Construcción de prompts para Claude.

El prompt final es: `system_prompt_del_tenant` + bloque opcional de contexto RAG.
El historial va aparte como `messages`.
"""

from __future__ import annotations


def format_knowledge_chunks(chunks: list[dict]) -> str:
    """Formatea los chunks recuperados de la KB para inyectar en el system prompt."""
    if not chunks:
        return ""
    parts = []
    for i, c in enumerate(chunks, start=1):
        title = c.get("document_title", "documento")
        sim = float(c.get("similarity", 0.0))
        content = c.get("content", "").strip()
        parts.append(f"### Fragmento {i} — '{title}' (similitud {sim:.2f})\n{content}")
    return "\n\n".join(parts)


def build_system_prompt(base_prompt: str, knowledge_chunks: list[dict]) -> str:
    """Compone el system prompt: base del tenant + (opcional) contexto RAG."""
    kb_block = format_knowledge_chunks(knowledge_chunks)
    if not kb_block:
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        "---\n"
        "## Contexto relevante de la base de conocimiento\n\n"
        f"{kb_block}\n\n"
        "---\n"
        "Si la respuesta no está claramente respaldada por este contexto, "
        "NO inventes — escala con razón explícita."
    )


def _coalesce_consecutive_same_role(messages: list[dict]) -> list[dict]:
    """Mergea mensajes consecutivos del mismo role.

    Claude exige alternancia user/assistant. Si en la conversación hubo
    `agent_human` seguido de `agent_ai` (ambos mapean a `assistant`), los unimos.
    """
    out: list[dict] = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": f"{out[-1]['content']}\n\n{m['content']}"}
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def build_message_history(conversation_history: list[dict]) -> list[dict]:
    """Convierte el historial DB al formato `messages` de Anthropic.

    Mapping de roles:
        customer        → user
        agent_ai        → assistant
        agent_human     → assistant

    `system` no debería estar en el historial (lo excluye `get_recent_messages`),
    pero si llegara se descarta.
    """
    msgs: list[dict] = []
    for m in conversation_history:
        db_role = m.get("role")
        if db_role == "customer":
            api_role = "user"
        elif db_role in ("agent_ai", "agent_human"):
            api_role = "assistant"
        else:
            continue  # role='system' u otros: ignorar
        content = m.get("content", "")
        if not content.strip():
            continue
        msgs.append({"role": api_role, "content": content})

    msgs = _coalesce_consecutive_same_role(msgs)

    # Claude exige que el último mensaje sea user. Si por algún edge case
    # no lo es, no podemos seguir — el caller debe garantizarlo persistiendo
    # el mensaje del cliente antes de invocar el grafo.
    if not msgs or msgs[-1]["role"] != "user":
        raise ValueError(
            "El historial debe terminar con un mensaje del cliente (role='user'). "
            "Verificá que el inbound se persistió antes de invocar el grafo."
        )
    return msgs
