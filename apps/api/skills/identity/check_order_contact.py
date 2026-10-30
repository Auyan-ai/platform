"""Skill de respaldo del nivel `guest` (ADR 0013 §4): el LLM transcribe, el código compara.

El nodo `resolve_identity` ya saca el número de pedido y el contacto del texto con
parsers. Si fallan (por ejemplo "mi pedido es el mil dos"), el LLM pasa aquí lo que
entendió y esta skill corre la misma `attempt_guest`, con los mismos límites y los mismos
textos fijos. El LLM nunca ve si un pedido existe: solo `verified` o el texto fijo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.db.client import tenant_scope
from apps.api.integrations.commerce import CommerceCapability
from apps.api.services.identity_guest import (
    Pair,
    can_lookup_orders,
    commerce_unavailable_refusal,
    extract_provided,
    normalize_order_ref,
    run_guest_checks,
)
from apps.api.skills.base import Skill, SkillContext, SkillInput, SkillOutput, SkillTier
from apps.api.skills.registry import SkillRegistry
from apps.api.skills.shopify.get_order_status import map_order_detail

NOTHING_CHECKED_NOTE = (
    "No se ha podido hacer una comprobación nueva: ese dato ya se comprobó antes en esta "
    "conversación o no se pudo reconocer. No digas si el pedido existe. Pide al cliente "
    "el número de pedido y el email o teléfono de la compra, o ofrécele pasar el caso a "
    "una persona del equipo."
)


class CheckOrderContactInput(SkillInput):
    order_number: str
    contact: str  # email o teléfono tal como lo escribió el cliente


class CheckOrderContactOutput(SkillOutput):
    verified: bool
    # El pedido ya proyectado (`OrderDetail`, el mismo que `get_order_status`).
    order: dict[str, Any] | None = None
    granted_order_id: int | None = None
    valid_until: datetime | None = None
    # Texto fijo que cierra el turno sin pasar por el LLM (no coincide, bloqueo, pausa).
    reply: str | None = None
    note: str | None = None


@SkillRegistry.register
class CheckOrderContact(Skill):
    slug = "identity.check_order_contact"
    required_capability = CommerceCapability.ORDER_READ
    description = (
        "Comprueba que el número de pedido y el email o teléfono que dio el cliente "
        "coinciden con el pedido. Úsala solo cuando el cliente ya los dio en la conversación "
        "y el sistema no los reconoció solo (por ejemplo, el número escrito en letras). "
        "Transcribe los datos tal cual, sin inventar ni completar ninguno. Si coinciden, "
        "devuelve el pedido y ya puedes consultarlo y gestionarlo."
    )
    tier: SkillTier = "L1"
    input_schema = CheckOrderContactInput
    output_schema = CheckOrderContactOutput
    default_threshold = 0.70
    core = True

    async def execute(self, ctx: SkillContext, inputs: SkillInput) -> SkillOutput:
        assert isinstance(inputs, CheckOrderContactInput)
        if not can_lookup_orders(ctx):
            raise ValueError("commerce_not_configured")
        contacts = extract_provided([inputs.contact], region=ctx.phone_region).contacts
        order_ref = normalize_order_ref(inputs.order_number)
        pairs = [Pair(order_ref, contact) for contact in contacts] if order_ref else []
        async with tenant_scope(UUID(ctx.tenant_id)) as conn:
            result = await run_guest_checks(
                conn,
                ctx,
                pairs,
                policy=ctx.guest_policy,
                tenant_facts=ctx.tenant_facts,
            )
        if result.status == "unavailable":
            raise commerce_unavailable_refusal(result.error or "", ctx)
        if result.status == "granted":
            grant = result.grants[0]
            return CheckOrderContactOutput(
                verified=True,
                order=map_order_detail(result.orders[0]).model_dump(mode="json"),
                granted_order_id=grant.order_id,
                valid_until=grant.valid_until,
            )
        if result.reply is not None:
            return CheckOrderContactOutput(verified=False, reply=result.reply)
        return CheckOrderContactOutput(verified=False, note=NOTHING_CHECKED_NOTE)
