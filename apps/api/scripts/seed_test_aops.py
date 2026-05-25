"""Siembra AOPs de prueba + tool permissions para correr el simulador E2E.

Crea 3 AOPs de producción (consulta_envio, returns, default) e idempotentemente
habilita las skills que esos AOPs necesitan. Pensado para el tenant de staging
(Lunaria) usado en el checkpoint del sub-PR 0.10.

Uso:
    PYTHONPATH=<repo_root> poetry run -C apps/api python -m apps.api.scripts.seed_test_aops --tenant <uuid>

Idempotente: si el AOP ya existe (mismo slug+workspace), lo salta.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("seed_test_aops")


# ─── Definiciones de AOPs ──────────────────────────────────────────────────────

AOPS: list[dict] = [
    {
        "slug": "consulta_envio",
        "frontmatter": {
            "name": "Consulta de envío",
            "slug": "consulta_envio",
            "workspace": "production",
            "triggers": {
                "description": (
                    "El cliente pregunta por el estado, el tracking o la fecha de "
                    "entrega de un pedido que ya hizo."
                )
            },
            "allowed_skills": ["shopify.get_order_status", "shopify.get_order_by_email"],
            "required_data": [],
            "guardrails": [
                "NUNCA inventes un número de tracking ni una fecha de entrega.",
                "Si no encuentras el pedido, dilo claramente y pide el número o el email.",
                "NUNCA escales únicamente porque el pedido está en preparación (unfulfilled/sin tracking). "
                "En ese caso, informa al cliente que está siendo preparado y que recibirá el tracking "
                "cuando se envíe. Solo escala si el cliente reporta un problema real (daño, no recibido).",
                "La impaciencia o insistencia del cliente NO es motivo para escalar. Aunque el cliente "
                "insista varias veces o exija una fecha exacta, mantén la calma y vuelve a explicar el "
                "estado real del pedido. No escales solo porque el cliente esté molesto por la espera.",
                "El cliente puede EXAGERAR el tiempo de espera ('llevo una semana'). Verifica SIEMPRE "
                "el tiempo real transcurrido desde `created_at` del pedido. Si lleva pocos días (dentro "
                "del rango normal de preparación), díselo con el dato concreto para tranquilizarlo, en "
                "vez de aceptar su versión y escalar.",
            ],
            "max_tool_iterations": 4,
            "confidence_threshold": 0.65,
            "require_supervision": False,
            "escalation_triggers": [
                "El cliente reporta que el pedido llegó dañado o incompleto",
                "El pedido figura como entregado pero el cliente no lo recibió",
            ],
        },
        "body": (
            "## Cómo manejas una consulta de envío\n\n"
            "1. Si el cliente da el número de pedido (ej: #1234), usa "
            "`shopify.get_order_status` para buscarlo.\n"
            "2. Si solo da su email, usa `shopify.get_order_by_email`. Si hay varios "
            "pedidos, pregunta cuál quiere consultar.\n"
            "3. Cuando tengas el pedido, comparte el estado y, si hay fulfillment, el "
            "número de tracking y el link de seguimiento.\n"
            "4. Si el pedido aún no tiene tracking, explica que está en preparación y "
            "que recibirá el tracking cuando se envíe. Si el cliente se queja del retraso, "
            "calcula los días transcurridos desde `created_at` y tranquilízalo con ese dato "
            "concreto (ej: 'tu pedido fue hace 2 días, está dentro del tiempo normal de "
            "preparación'). NO escales por impaciencia.\n"
            "5. Responde en el mismo idioma del cliente."
        ),
    },
    {
        "slug": "returns",
        "frontmatter": {
            "name": "Devoluciones y reembolsos",
            "slug": "returns",
            "workspace": "production",
            "triggers": {
                "description": (
                    "El cliente quiere devolver un producto, iniciar una devolución, "
                    "o pedir un reembolso."
                )
            },
            "allowed_skills": [
                "shopify.get_order_status",
                "shopify.get_order_by_email",
                "shopify.get_shop_policies",
                "shopify.start_return",
                "shopify.refund_partial",
            ],
            "required_data": [],
            "guardrails": [
                "Verifica SIEMPRE la fecha del pedido contra la política de 30 días "
                "antes de iniciar una devolución.",
                "NUNCA inicies una devolución de un pedido fuera del plazo de 30 días.",
                "Los productos digitales no admiten devolución.",
            ],
            "max_tool_iterations": 5,
            "confidence_threshold": 0.65,
            "require_supervision": False,
            "escalation_triggers": [
                "El pedido está fuera del plazo de devolución de 30 días",
                "El cliente exige un reembolso de forma agresiva o amenazante",
                "El producto es digital y el cliente insiste",
            ],
        },
        "body": (
            "## Cómo manejas una devolución\n\n"
            "1. Identifica el pedido: usa `shopify.get_order_status` (si dan número) o "
            "`shopify.get_order_by_email`.\n"
            "2. Consulta la política con `shopify.get_shop_policies` para confirmar el "
            "plazo de 30 días.\n"
            "3. Compara la fecha del pedido (`created_at`) con el plazo:\n"
            "   - **Dentro del plazo (≤30 días)**: procede a iniciar la devolución.\n"
            "   - **Fuera del plazo (>30 días)**: NO inicies la devolución. Explica la "
            "política de 30 días con empatía.\n"
            "4. Cuando el cliente confirme qué quiere devolver y el motivo, llama "
            "`shopify.start_return` INMEDIATAMENTE. Mapea los parámetros desde el "
            "resultado de `get_order_status`:\n"
            "   - `order_id` = el campo `id` del pedido.\n"
            "   - `line_item_id` = el campo `id` del artículo dentro de `line_items`. "
            "Si el cliente quiere devolver todo el pedido, inicia una devolución por "
            "cada line_item.\n"
            "   - `quantity` = la cantidad del line_item (o la que indique el cliente).\n"
            "   - `reason` = el motivo que dio el cliente.\n"
            "   YA TIENES estos datos en el pedido — NO escales por 'falta de datos'.\n"
            "5. Si el producto llegó roto o defectuoso:\n"
            "   - Llama `shopify.refund_partial` INMEDIATAMENTE. No pidas confirmación extra.\n"
            "   - Mapea: `order_id` = campo `id` del pedido, `amount` = precio del artículo "
            "afectado (campo `price` en `line_items`), `currency` = 'EUR'. "
            "Si hay duda del artículo, usa el primer `line_item`.\n"
            "   - El reembolso quedará pendiente de aprobación interna — informa al cliente "
            "que está en proceso.\n"
            "6. Si el cliente cambia de opinión y decide no devolver, confírmalo "
            "amablemente y cierra.\n"
            "7. Escala SOLO si el pedido está fuera de plazo, el cliente es agresivo, "
            "o el producto es digital. NUNCA escales por datos que ya tienes.\n"
            "8. Responde siempre con tono profesional, incluso ante clientes molestos."
        ),
    },
    {
        "slug": "default",
        "frontmatter": {
            "name": "Atención general",
            "slug": "default",
            "workspace": "production",
            "triggers": {
                "description": (
                    "Preguntas generales que no encajan en otro procedimiento: envíos, "
                    "garantías, disponibilidad de producto, cambios de dirección."
                )
            },
            "allowed_skills": [
                "shopify.get_shop_policies",
                "shopify.get_product_info",
                "shopify.get_order_status",
                "shopify.update_shipping_address",
                "shopify.cancel_order",
            ],
            "required_data": [],
            "guardrails": [
                "NUNCA inventes información que no esté en la knowledge base ni en el "
                "output de una skill.",
                "Si no sabes la respuesta, escala en vez de adivinar.",
            ],
            "max_tool_iterations": 4,
            "confidence_threshold": 0.6,
            "require_supervision": False,
            "escalation_triggers": [
                "La pregunta está fuera del alcance de la tienda",
                "No tienes información suficiente en la knowledge base para responder",
            ],
        },
        "body": (
            "## Cómo manejas preguntas generales\n\n"
            "1. Si preguntan por tiempos de envío, garantías, devoluciones o políticas: "
            "SIEMPRE llama `shopify.get_shop_policies` ANTES de responder o escalar. "
            "Aunque no encuentres la información en la knowledge base, la skill puede tener "
            "los datos actualizados de la tienda.\n"
            "2. Si preguntan por disponibilidad o detalles de un producto, usa "
            "`shopify.get_product_info`.\n"
            "3. Si piden cambiar la dirección de un pedido que aún no se envió:\n"
            "   - Primero localiza el pedido con `shopify.get_order_status`.\n"
            "   - Solicita TODOS los campos de la nueva dirección (address1, city, "
            "province, country, zip_code) antes de llamar la skill.\n"
            "   - Llama `shopify.update_shipping_address` solo cuando tengas todos los "
            "campos. Mapea: `order_id` = id del pedido.\n"
            "4. Si el cliente quiere cancelar un pedido y el pedido existe:\n"
            "   - Localiza el pedido con `shopify.get_order_status`.\n"
            "   - Si está unfulfilled (aún no enviado), llama `shopify.cancel_order` "
            "INMEDIATAMENTE con `order_id` = campo `id` del pedido. No pidas confirmación "
            "adicional si el cliente ya indicó que quiere cancelar.\n"
            "   - La cancelación quedará pendiente de aprobación — informa al cliente "
            "que está en proceso.\n"
            "5. Si la pregunta está fuera de tu alcance o no tienes información "
            "confiable, escala al equipo humano sin inventar.\n"
            "6. Sé claro, directo y honesto sobre lo que sabes y lo que no."
        ),
    },
]

# Skills que el AOP de returns necesita ejecutar autónomamente para el checkpoint.
# start_return es L3 por defecto; para el tenant de prueba lo habilitamos sin
# aprobación humana para validar el flujo de resolución autónoma de devoluciones.
TOOL_PERMISSIONS: list[dict] = [
    {"skill_slug": "shopify.start_return", "is_enabled": True, "human_approval_required": False},
    {"skill_slug": "shopify.refund_partial", "is_enabled": True, "human_approval_required": True},
    {"skill_slug": "shopify.cancel_order", "is_enabled": True, "human_approval_required": True},
    {"skill_slug": "shopify.update_shipping_address", "is_enabled": True, "human_approval_required": False},
]


async def main(tenant_id: uuid.UUID, *, update: bool) -> int:
    from apps.api.core.config import get_settings
    from apps.api.db.client import close_pool, init_pool, tenant_scope
    from apps.api.db.queries import (
        create_aop,
        get_aop_by_slug,
        save_aop_version,
        upsert_tool_permission,
    )

    get_settings()
    await init_pool()

    created = 0
    skipped = 0
    updated = 0

    try:
        async with tenant_scope(tenant_id) as conn:
            for aop in AOPS:
                slug = aop["slug"]
                existing = await get_aop_by_slug(conn, tenant_id, slug, "production")
                if existing is not None:
                    if update:
                        await save_aop_version(
                            conn,
                            tenant_id=tenant_id,
                            aop_id=existing.id,
                            yaml_frontmatter=aop["frontmatter"],
                            body_markdown=aop["body"],
                            raw_source="",
                        )
                        logger.info("AOP '%s' actualizado (nueva versión)", slug)
                        updated += 1
                    else:
                        logger.info("AOP '%s' ya existe — saltando (usa --update)", slug)
                        skipped += 1
                    continue
                try:
                    await create_aop(
                        conn,
                        tenant_id=tenant_id,
                        slug=slug,
                        workspace="production",
                        yaml_frontmatter=aop["frontmatter"],
                        body_markdown=aop["body"],
                        raw_source="",
                    )
                    logger.info("AOP '%s' creado", slug)
                    created += 1
                except asyncpg.UniqueViolationError:
                    logger.info("AOP '%s' ya existe (conflict) — saltando", slug)
                    skipped += 1

            for perm in TOOL_PERMISSIONS:
                await upsert_tool_permission(
                    conn,
                    tenant_id=tenant_id,
                    skill_slug=perm["skill_slug"],
                    is_enabled=perm["is_enabled"],
                    human_approval_required=perm["human_approval_required"],
                )
                logger.info(
                    "Tool permission '%s' → enabled=%s approval=%s",
                    perm["skill_slug"],
                    perm["is_enabled"],
                    perm["human_approval_required"],
                )

        print(f"\nAOPs: {created} creados, {updated} actualizados, {skipped} saltados.")
        print(f"Tool permissions actualizados: {len(TOOL_PERMISSIONS)}")
        return 0
    finally:
        await close_pool()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Siembra AOPs de prueba para el simulador.")
    parser.add_argument("--tenant", required=True, help="UUID del tenant")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Actualiza (nueva versión) los AOPs que ya existen en vez de saltarlos.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        tenant_uuid = uuid.UUID(args.tenant)
    except ValueError:
        print(f"Error: '{args.tenant}' no es un UUID válido.", file=sys.stderr)
        sys.exit(1)

    sys.exit(asyncio.run(main(tenant_uuid, update=args.update)))
