"""EmailSender — envío de emails outbound Auyan→cliente (fire-and-forget).

Mismo patrón que ReasoningTracker y AuditLogger: el caller no espera resultado.
Si el envío falla, se loguea el error pero no afecta el flujo principal.

Si POSTMARK_API_TOKEN no está configurado (adapter=None), todas las llamadas
son no-op con un warning en logs. El sistema funciona sin Postmark en local.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from apps.api.integrations.postmark import PostmarkEmailAdapter

logger = logging.getLogger(__name__)


class EmailSender:
    """Servicio de email outbound. Instanciar una vez en startup.

    Args:
        adapter: PostmarkEmailAdapter instanciado con creds globales de Auyan,
                 o None si POSTMARK_API_TOKEN no está configurado.
    """

    _pending_tasks: ClassVar[set[asyncio.Task[Any]]] = set()

    def __init__(self, adapter: PostmarkEmailAdapter | None) -> None:
        self._adapter = adapter
        if adapter is None:
            logger.warning(
                "email_sender_no_adapter: POSTMARK_API_TOKEN not configured — emails disabled"
            )

    # ── API pública ────────────────────────────────────────────────────────────

    def send_email(
        self,
        *,
        to: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        tag: str | None = None,
    ) -> None:
        """Encola el envío de un email genérico (fire-and-forget)."""
        if self._adapter is None:
            logger.warning(
                "email_send_skipped to=%s subject=%r adapter_not_configured", to, subject
            )
            return
        self._schedule(
            lambda: self._adapter.send_email(
                to=to,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                tag=tag,
            ),
            name=f"email_send_{to}",
        )

    async def send_email_now(
        self,
        *,
        to: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        """Envía un email y devuelve la respuesta del adapter.

        Útil para flujos que necesitan persistir un resultado exacto, como
        reportes semanales marcados como `sent`.
        """
        if self._adapter is None:
            raise RuntimeError("email_adapter_not_configured")
        return await self._adapter.send_email(
            to=to,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            tag=tag,
        )

    def send_escalation_fallback(
        self,
        *,
        to_email: str,
        tenant_name: str,
        conversation_id: str,
        reason: str,
        customer_email: str | None = None,
        agent_summary: str | None = None,
    ) -> None:
        """Notifica al equipo CX del cliente sobre una escalación sin helpdesk.

        Se usa cuando el tenant no tiene un helpdesk configurado y el agente
        necesita escalar — el email es el fallback para avisar al equipo humano.
        """
        if self._adapter is None:
            logger.warning(
                "escalation_fallback_email_skipped "
                "tenant=%s conversation=%s adapter_not_configured",
                tenant_name,
                conversation_id,
            )
            return

        from apps.api.services.email_templates import escalation_fallback

        subject, text_body, html_body = escalation_fallback.render(
            tenant_name=tenant_name,
            conversation_id=conversation_id,
            reason=reason,
            customer_email=customer_email,
            agent_summary=agent_summary,
        )
        self._schedule(
            lambda: self._adapter.send_email(
                to=to_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                tag="escalation-fallback",
            ),
            name=f"escalation_fallback_{conversation_id}",
        )

    # ── Internals ──────────────────────────────────────────────────────────────

    def _schedule(self, coro_factory: Callable[[], Awaitable[Any]], *, name: str) -> None:
        """Crea un asyncio.Task y lo registra en _pending_tasks."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("email_send_no_event_loop name=%s", name)
            return

        task = loop.create_task(coro_factory(), name=name)
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        task.add_done_callback(self._log_task_error)

    @staticmethod
    def _log_task_error(task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "email_send_failed task=%s error=%s",
                task.get_name(),
                task.exception(),
            )
