"""Alerta de caída total del proveedor LLM (saldo agotado, key inválida, sin permisos).

Cada fallo: log `error` con categoría `llm_provider_unavailable` (alertable por severidad en
Cloud Run). Además un email a `ALERT_EMAIL_TO` vía Postmark, como mucho uno por hora y proceso.
La API corre con una sola instancia en Cloud Run (`max=1`), así que la deduplicación en memoria
basta; con más instancias habría una alerta por instancia y hora.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from apps.api.integrations.anthropic_client import PROVIDER_UNAVAILABLE_CATEGORY

logger = logging.getLogger(__name__)

ALERT_COOLDOWN_SECONDS = 3600


class AlertSender(Protocol):
    async def send_email_now(
        self,
        *,
        to: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]: ...


class LLMProviderAlerter:
    def __init__(
        self,
        sender: AlertSender | None,
        to: str | None,
        *,
        cooldown_seconds: float = ALERT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sender = sender
        self._to = to
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._last_sent: float | None = None

    async def report(
        self,
        *,
        reason: str,
        status_code: int | None,
        detail: str,
        tenant_id: str | None,
        conversation_id: str | None,
    ) -> bool:
        """Loguea siempre; manda el email si no hubo otro en la última hora. True si lo mandó."""
        logger.error(
            "%s reason=%s status=%s",
            PROVIDER_UNAVAILABLE_CATEGORY,
            reason,
            status_code,
            extra={
                "category": PROVIDER_UNAVAILABLE_CATEGORY,
                "reason": reason,
                "status_code": status_code,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
            },
        )
        now = self._clock()
        if self._last_sent is not None and now - self._last_sent < self._cooldown:
            return False
        if self._sender is None or not self._to:
            logger.error(
                "llm_provider_alert_not_sent: falta POSTMARK_API_TOKEN o ALERT_EMAIL_TO",
                extra={"category": PROVIDER_UNAVAILABLE_CATEGORY},
            )
            return False
        # Se reserva el hueco antes de enviar para que turnos concurrentes no dupliquen.
        previous, self._last_sent = self._last_sent, now
        subject = f"[Auyan] Agente caído: Anthropic rechaza las llamadas ({reason})"
        body = (
            "Anthropic rechaza todas las llamadas del agente, así que cada turno escala al "
            "helpdesk del cliente sin respuesta del agente.\n\n"
            f"Motivo: {reason}\n"
            f"Estado HTTP: {status_code}\n"
            f"Detalle: {detail}\n"
            f"Primer turno afectado: tenant={tenant_id} conversación={conversation_id}\n\n"
            "Qué hacer: recargar saldo o revisar ANTHROPIC_API_KEY (console.anthropic.com). "
            "Próxima alerta como pronto en 1 hora; los fallos siguen en los logs "
            f"con categoría {PROVIDER_UNAVAILABLE_CATEGORY}."
        )
        try:
            await self._sender.send_email_now(
                to=self._to, subject=subject, text_body=body, tag="llm-provider-unavailable"
            )
        except Exception:
            self._last_sent = previous
            logger.exception(
                "llm_provider_alert_send_failed",
                extra={"category": PROVIDER_UNAVAILABLE_CATEGORY},
            )
            return False
        logger.info("llm_provider_alert_sent reason=%s", reason)
        return True


_alerter: LLMProviderAlerter | None = None


def configure_alerter(alerter: LLMProviderAlerter | None) -> None:
    global _alerter
    _alerter = alerter


async def report_provider_unavailable(
    *,
    reason: str,
    status_code: int | None,
    detail: str,
    tenant_id: str | None,
    conversation_id: str | None,
) -> bool:
    """Punto de entrada de los nodos. Sin alerter configurado (tests, scripts) solo loguea."""
    alerter = _alerter or LLMProviderAlerter(None, None)
    return await alerter.report(
        reason=reason,
        status_code=status_code,
        detail=detail,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
