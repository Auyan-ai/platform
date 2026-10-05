"""Triggers de Zendesk del handoff de WhatsApp: definición canónica (ADR 0010).

Única fuente de qué triggers y webhook necesita una cuenta de Zendesk para la vuelta del
handoff. La usan `scripts/setup_zendesk_handoff_triggers.py` (crea/actualiza) y el doctor
del tenant (`services/doctor`, comprueba que lo que hay en la cuenta coincide).
"""

from __future__ import annotations

import json
from typing import Any

from apps.api.integrations.zendesk import (
    ZENDESK_ADMIN_SCOPES,
    ZendeskClient,
    fetch_client_credentials_token,
)

HANDOFF_TAG = "auyan_handoff"
REPLY_TITLE = "Auyan · handoff · respuesta"
SOLVED_TITLE = "Auyan · handoff · resuelto"
COMMENT_ID_PLACEHOLDER = "{% for c in ticket.comments limit:1 %}{{c.id}}{% endfor %}"
NOT_HANDOFF_CONDITION = {"field": "current_tags", "operator": "not_includes", "value": HANDOFF_TAG}


def webhook_body(subdomain: str, event: str, *, with_comment: bool) -> str:
    body: dict[str, str] = {"ticket_id": "{{ticket.id}}"}
    if with_comment:
        body["comment_id"] = COMMENT_ID_PLACEHOLDER
    body["subdomain"] = subdomain
    body["event"] = event
    return json.dumps(body, ensure_ascii=False)


def reply_trigger(webhook_id: str, subdomain: str) -> dict[str, Any]:
    return {
        "title": REPLY_TITLE,
        "conditions": {
            "all": [
                {"field": "update_type", "operator": "is", "value": "Change"},
                {"field": "current_tags", "operator": "includes", "value": HANDOFF_TAG},
                {"field": "comment_is_public", "operator": "is", "value": "true"},
                {"field": "role", "operator": "is", "value": "agent"},
            ],
            "any": [],
        },
        "actions": [
            {
                "field": "notification_webhook",
                "value": [webhook_id, webhook_body(subdomain, "handoff_reply", with_comment=True)],
            }
        ],
    }


def solved_trigger(webhook_id: str, subdomain: str) -> dict[str, Any]:
    return {
        "title": SOLVED_TITLE,
        "conditions": {
            "all": [
                # En la API de Zendesk "cambió a" es `value` (`changed_to` → 422).
                {"field": "status", "operator": "value", "value": "solved"},
                {"field": "current_tags", "operator": "includes", "value": HANDOFF_TAG},
            ],
            "any": [],
        },
        "actions": [
            {
                "field": "notification_webhook",
                "value": [
                    webhook_id,
                    webhook_body(subdomain, "handoff_solved", with_comment=False),
                ],
            }
        ],
    }


def _webhook_action(trigger: dict[str, Any]) -> tuple[str, str] | None:
    for action in trigger.get("actions") or []:
        value = action.get("value")
        if action.get("field") == "notification_webhook" and isinstance(value, list):
            return str(value[0]), str(value[1] if len(value) > 1 else "")
    return None


def find_inbound_triggers(triggers: list[dict[str, Any]], webhook_id: str) -> list[dict[str, Any]]:
    """Triggers que notifican a nuestro webhook y NO son los del handoff (el de inbound)."""
    found = []
    for trigger in triggers:
        action = _webhook_action(trigger)
        if action and action[0] == webhook_id and "handoff_" not in action[1]:
            found.append(trigger)
    return found


def with_not_handoff_condition(trigger: dict[str, Any]) -> dict[str, Any] | None:
    """Condiciones del trigger de inbound con `tags no incluye auyan_handoff`; None si ya está."""
    conditions = trigger.get("conditions") or {}
    all_conditions = list(conditions.get("all") or [])
    if NOT_HANDOFF_CONDITION in all_conditions:
        return None
    return {"all": [*all_conditions, NOT_HANDOFF_CONDITION], "any": conditions.get("any") or []}


def inbound_trigger_update(trigger: dict[str, Any]) -> dict[str, Any] | None:
    """Body del PUT al trigger de inbound; None si ya excluye el handoff.

    Zendesk valida el trigger entero en el PUT: sin `actions` responde 422 ("debe contener
    por lo menos una acción"), así que se reenvían las suyas tal cual.
    """
    conditions = with_not_handoff_condition(trigger)
    if conditions is None:
        return None
    return {"trigger": {"conditions": conditions, "actions": trigger.get("actions") or []}}


def find_auyan_webhook(webhooks: list[dict[str, Any]], api_base_url: str | None) -> dict | None:
    for webhook in webhooks:
        endpoint = str(webhook.get("endpoint") or "")
        if endpoint.endswith("/webhooks/zendesk") and (
            api_base_url is None or endpoint.startswith(api_base_url.rstrip("/"))
        ):
            return webhook
    return None


async def admin_client(creds: dict[str, Any], subdomain: str) -> ZendeskClient:
    """Cliente con scope de administración (triggers y webhooks). Con client credentials
    pide un token `read write`; con OAuth o API token usa lo que haya concedido el cliente."""
    if creds.get("client_id") and creds.get("client_secret"):
        token, _ = await fetch_client_credentials_token(
            subdomain, creds["client_id"], creds["client_secret"], scope=ZENDESK_ADMIN_SCOPES
        )
        return ZendeskClient(subdomain, oauth_token=token)
    return ZendeskClient(
        subdomain,
        oauth_token=creds.get("oauth_token"),
        email=creds.get("email"),
        api_token=creds.get("api_token"),
    )
