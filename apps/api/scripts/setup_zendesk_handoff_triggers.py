"""Triggers de Zendesk para la vuelta del handoff de WhatsApp (idempotente).

Crea o actualiza, vía la Triggers API y el webhook de Zendesk que YA apunta a Auyan
(`…/webhooks/zendesk`):

- **Auyan · handoff · respuesta**: ticket actualizado, tag `auyan_handoff`, comentario
  público y usuario actual agente → `{"ticket_id","comment_id","subdomain","event":"handoff_reply"}`.
- **Auyan · handoff · resuelto**: estado cambia a `solved` con el tag →
  `{"ticket_id","subdomain","event":"handoff_solved"}`.
- Al trigger de inbound existente le añade `tags no incluye auyan_handoff` (el código también
  lo filtra: doble capa anti-loop).
- Guarda `api_user_id` (usuario API de Auyan en Zendesk) en la config de la integración: sus
  comentarios nunca se reenvían al comprador.

Uso (desde apps/api con `.env.staging` cargado: DATABASE_URL + INTEGRATIONS_SECRET_KEY):

    python -m scripts.setup_zendesk_handoff_triggers --tenant marea-studio --dry-run
    python -m scripts.setup_zendesk_handoff_triggers --tenant marea-studio
"""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.api.db.queries import get_active_integration, upsert_integration
from apps.api.integrations.zendesk import (
    ZENDESK_ADMIN_SCOPES,
    ZendeskClient,
    fetch_client_credentials_token,
)
from apps.api.scripts.configure_staging_integrations import (
    _connect_database,
    _integration_key_from_env,
    _require_env,
)
from apps.api.scripts.onboard_whatsapp import _resolve_tenant_id
from apps.api.services.integrations_crypto import decrypt_credentials

HANDOFF_TAG = "auyan_handoff"
REPLY_TITLE = "Auyan · handoff · respuesta"
SOLVED_TITLE = "Auyan · handoff · resuelto"
COMMENT_ID_PLACEHOLDER = "{% for c in ticket.comments limit:1 %}{{c.id}}{% endfor %}"
NOT_HANDOFF_CONDITION = {"field": "current_tags", "operator": "not_includes", "value": HANDOFF_TAG}


# ─── Definiciones puras (testeables) ──────────────────────────────────────────


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
                {"field": "status", "operator": "changed_to", "value": "solved"},
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


def find_auyan_webhook(webhooks: list[dict[str, Any]], api_base_url: str | None) -> dict | None:
    for webhook in webhooks:
        endpoint = str(webhook.get("endpoint") or "")
        if endpoint.endswith("/webhooks/zendesk") and (
            api_base_url is None or endpoint.startswith(api_base_url.rstrip("/"))
        ):
            return webhook
    return None


# ─── Ejecución ────────────────────────────────────────────────────────────────


async def _admin_client(creds: dict[str, Any], subdomain: str) -> ZendeskClient:
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


async def run(args: argparse.Namespace) -> None:
    key = _integration_key_from_env()
    conn = await _connect_database(_require_env("DATABASE_URL"))
    try:
        tenant_id = await _resolve_tenant_id(conn, args.tenant)
        integration = await get_active_integration(
            conn, tenant_id=tenant_id, kind="helpdesk", provider="zendesk"
        )
        if integration is None:
            raise SystemExit("El tenant no tiene Zendesk activo.")
        row = await conn.fetchrow(
            "SELECT credentials_encrypted FROM tenant_integrations WHERE id = $1", integration.id
        )
        creds = json.loads(decrypt_credentials(bytes(row["credentials_encrypted"]), key).decode())
        subdomain = integration.config["subdomain"]
        client = await _admin_client(creds, subdomain)

        webhooks = (await client._request("GET", "/webhooks")).get("webhooks") or []
        webhook = find_auyan_webhook(webhooks, args.api_base_url)
        if webhook is None:
            raise SystemExit("No encuentro el webhook de Zendesk que apunta a /webhooks/zendesk.")
        webhook_id = str(webhook["id"])
        triggers = (await client._request("GET", "/triggers.json")).get("triggers") or []
        by_title = {t.get("title"): t for t in triggers}

        plan: list[tuple[str, str, dict[str, Any]]] = []
        for definition in (
            reply_trigger(webhook_id, subdomain),
            solved_trigger(webhook_id, subdomain),
        ):
            existing = by_title.get(definition["title"])
            if existing is None:
                plan.append(("POST", "/triggers.json", {"trigger": definition}))
            else:
                plan.append(("PUT", f"/triggers/{existing['id']}.json", {"trigger": definition}))
        for inbound in find_inbound_triggers(triggers, webhook_id):
            conditions = with_not_handoff_condition(inbound)
            if conditions is not None:
                plan.append(
                    (
                        "PUT",
                        f"/triggers/{inbound['id']}.json",
                        {"trigger": {"conditions": conditions}},
                    )
                )
        me = await client.get_me()

        for method, path, body in plan:
            print(method, path, json.dumps(body, ensure_ascii=False)[:300])
        print(f"api_user_id = {me['id']}")
        if args.dry_run:
            return
        for method, path, body in plan:
            await client._request(method, path, json_body=body)
        config = {**(integration.config or {}), "api_user_id": str(me["id"])}
        await upsert_integration(
            conn,
            tenant_id=tenant_id,
            kind="helpdesk",
            provider="zendesk",
            credentials_encrypted=bytes(row["credentials_encrypted"]),
            config=config,
            is_active=True,
            is_primary_for_kind=integration.is_primary_for_kind,
        )
        print("OK: triggers del handoff listos y api_user_id guardado.")
    except httpx.HTTPStatusError as exc:
        raise SystemExit(
            f"Zendesk HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    finally:
        await conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Triggers de Zendesk para el handoff de WhatsApp")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--api-base-url", default=None, help="Filtra el webhook por su URL base")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    asyncio.run(run(_parse_args()))
