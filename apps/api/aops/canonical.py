"""Canonical AOPs de Auyan — los 8 procedimientos por defecto de e-commerce ES.

Fuente de verdad EN CÓDIGO. `provision_tenant` los siembra al crear cada tenant
(copy-on-create): cada tenant recibe SU PROPIA copia (filas en aops/aop_versions),
editable de forma aislada desde el dashboard interno sin afectar a otros tenants.

- Mejorar un default = editar este módulo → los tenants NUEVOS lo heredan automáticamente;
  los EXISTENTES vía `scripts/seed_canonical_aops.py --update`.
- A propósito NO se usa un "tenant template" en DB: un tenant fantasma se filtraría en
  listas/billing/inbox y contaminaría el modelo multi-tenant (regla dura de CLAUDE.md).
- `raw_source` se genera en formato '---\\nYAML\\n---\\nbody' para que el editor del
  dashboard (routers/aops.py::_parse_raw_source) pueda round-tripear y editarlos.

Postura de autonomía (tool_permissions default): L1/L2 autónomos; los 4 L3 nacen
`enabled` + `human_approval_required=true`. super_admin gradúa por cliente.

Diseño completo, fronteras y razones: docs/aop-canonical-design.md.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import asyncpg
import yaml
from apps.api.db.queries import (
    create_aop,
    get_aop_by_slug,
    save_aop_version,
    upsert_tool_permission,
)

logger = logging.getLogger(__name__)

CANONICAL_WORKSPACE = "production"


# ─── Definiciones de los 8 AOPs canónicos ─────────────────────────────────────
# Tenant-agnósticos: cero constantes de tienda (plazos/moneda/tiempos salen de
# tenant_facts, get_shop_policies o del propio pedido).

CANONICAL_AOPS: list[dict[str, Any]] = [
    {
        "slug": "order_status",
        "frontmatter": {
            "name": "Estado de pedido",
            "slug": "order_status",
            "workspace": CANONICAL_WORKSPACE,
            "triggers": {
                "description": (
                    "El cliente pregunta por el estado, ubicación, tracking o fecha de "
                    "entrega de un pedido que YA realizó. NO es: iniciar devolución "
                    "(returns), cancelar/cambiar dirección (order_change), ni dudas de "
                    "envío pre-compra (shipping_info)."
                ),
                "examples": [
                    "¿dónde está mi pedido?",
                    "no me ha llegado lo que compré",
                    "¿me das el tracking del #1234?",
                    "¿cuándo llega mi compra?",
                ],
            },
            "allowed_skills": [
                "shopify.get_order_status",
                "shopify.get_order_by_email",
            ],
            "required_data": [
                "Identificador del pedido: nº de pedido O el email de la compra",
            ],
            "guardrails": [
                "Nunca inventes tracking, transportista ni fecha de entrega: solo lo que devuelva la skill.",
                "Pedido 'unfulfilled' (en preparación, sin tracking) es normal; NO escales por eso.",
                "La impaciencia no es motivo de escalado: recalcula los días desde created_at y tranquiliza con el dato real.",
            ],
            "max_tool_iterations": 4,
            "confidence_threshold": 0.65,
            "require_supervision": False,
            "escalation_triggers": [
                "El cliente reporta el pedido dañado o incompleto",
                "El pedido figura entregado pero el cliente dice no haberlo recibido",
            ],
        },
        "body": (
            "## Procedimiento: estado de pedido\n"
            "Objetivo: decirle al cliente dónde está su pedido con datos reales, sin inventar.\n\n"
            "1. Si dio nº de pedido (#1234) → `shopify.get_order_status`. Si dio solo email → `shopify.get_order_by_email`.\n"
            "2. Si no dio ninguno → pídele el nº de pedido o el email de la compra antes de consultar.\n"
            "3. Si el email tiene varios pedidos → pregúntale cuál (menciónalos por fecha y nº).\n"
            "4. Con el pedido:\n"
            "   - Con tracking → comparte estado + transportista + nº de tracking + link de seguimiento.\n"
            "   - Sin tracking (en preparación) → dilo como algo normal; si se queja del retraso, calcula\n"
            "     los días desde `created_at` y tranquilízalo con ese dato concreto.\n"
            "5. Cierra preguntando si necesita algo más."
        ),
    },
    {
        "slug": "shipping_info",
        "frontmatter": {
            "name": "Información de envío",
            "slug": "shipping_info",
            "workspace": CANONICAL_WORKSPACE,
            "triggers": {
                "description": (
                    "Dudas GENERALES de envío: plazos, costes, zonas/países, métodos, "
                    "envío gratis. Normalmente pre-compra o de política. NO es el estado "
                    "de un pedido concreto ya hecho (eso es order_status), ni devoluciones."
                ),
                "examples": [
                    "¿cuánto tarda en llegar un pedido?",
                    "¿hacéis envíos a Canarias / Baleares?",
                    "¿el envío es gratis a partir de cuánto?",
                ],
            },
            "allowed_skills": [
                "shopify.get_shop_policies",
            ],
            "required_data": [],
            "guardrails": [
                "No inventes plazos, costes ni zonas: usa el contexto de la KB o get_shop_policies. Si no está, dilo y escala.",
                "No confundas tiempo de envío (en tránsito) con tiempo de preparación.",
            ],
            "max_tool_iterations": 3,
            "confidence_threshold": 0.60,
            "require_supervision": False,
            "escalation_triggers": [
                "Destino/país fuera de la cobertura conocida de la tienda",
                "Dudas de aduanas/impuestos de importación que la política no cubre",
            ],
        },
        "body": (
            "## Procedimiento: información de envío\n"
            "Objetivo: responder dudas generales de envío con la política real de la tienda y la KB.\n\n"
            "1. Apóyate en DOS fuentes: el contexto de la KB inyectado (si lo hay) y `get_shop_policies`.\n"
            "   Si falta el dato en ambas, no inventes: dilo y escala.\n"
            "2. Si preguntan por un destino concreto → confirma cobertura; si no está, dilo y escala.\n"
            "3. Distingue preparación vs tránsito al dar plazos.\n"
            "4. Si en realidad preguntan por SU pedido concreto → es order_status; el grafo reclasifica."
        ),
    },
    {
        "slug": "returns",
        "frontmatter": {
            "name": "Devoluciones",
            "slug": "returns",
            "workspace": CANONICAL_WORKSPACE,
            "triggers": {
                "description": (
                    "El cliente quiere devolver un producto / iniciar una devolución (la "
                    "MERCANCÍA de vuelta). Si pide SOLO el dinero sin devolver producto → "
                    "refunds. Cancelar un pedido no enviado → order_change. Producto "
                    "dañado/no recibido → complaint."
                ),
                "examples": [
                    "quiero devolver esta camiseta",
                    "¿cómo inicio una devolución?",
                    "el producto no me sirve, lo quiero devolver",
                ],
            },
            "allowed_skills": [
                "shopify.get_order_status",
                "shopify.get_order_by_email",
                "shopify.get_shop_policies",
                "shopify.start_return",
            ],
            "required_data": [
                "Identificador del pedido (nº o email)",
                "Qué artículo(s) quiere devolver y el motivo",
            ],
            "guardrails": [
                "Confirma elegibilidad con la política REAL (KB inyectada / tenant_facts / get_shop_policies), nunca con un plazo asumido.",
                "Fuera del plazo de la tienda → no inicies la devolución: explícalo con empatía y escala si insiste.",
                "Productos excluidos por la política (digitales/perecederos) no admiten devolución.",
                "No inicies start_return hasta tener artículo y motivo confirmados por el cliente.",
            ],
            "max_tool_iterations": 5,
            "confidence_threshold": 0.70,
            "require_supervision": True,
            "escalation_triggers": [
                "El pedido está fuera del plazo de devolución de la tienda",
                "El cliente es agresivo o amenazante",
                "La política excluye el producto y el cliente insiste",
            ],
        },
        "body": (
            "## Procedimiento: devolución\n"
            "Objetivo: ayudar a devolver un producto elegible, según la política real de la tienda.\n\n"
            "1. Identifica el pedido: nº → get_order_status; email → get_order_by_email.\n"
            "2. Determina plazo, condiciones y exclusiones desde la política REAL, en este orden de fuentes:\n"
            "   el contexto de la KB inyectado (si lo hay), `tenant_facts` (p.ej. plazo de devolución) y `get_shop_policies`.\n"
            "   No asumas un plazo que no esté en NINGUNA de esas fuentes; si falta en todas, dilo y escala.\n"
            "3. Elegibilidad: compara created_at con el plazo usando la fecha y hora actual de la tienda.\n"
            "   - Elegible → continúa.\n"
            "   - Fuera de plazo / excluido → explícalo con empatía, no inicies, escala si insiste.\n"
            "4. Confirma con el cliente QUÉ artículo(s) y el MOTIVO.\n"
            "5. start_return mapeando desde el pedido (order_id, line_item_id, quantity, reason). Queda en aprobación.\n"
            "   Explica el siguiente paso: enviar el producto, y que el reembolso se emite cuando se reciba y verifique.\n"
            "6. Si solo quiere el dinero (sin devolver) o pregunta por un reembolso → es refunds; el grafo reclasifica.\n"
            "7. Tono profesional siempre."
        ),
    },
    {
        "slug": "refunds",
        "frontmatter": {
            "name": "Reembolsos",
            "slug": "refunds",
            "workspace": CANONICAL_WORKSPACE,
            "triggers": {
                "description": (
                    "El cliente pregunta por el ESTADO de un reembolso en curso, o pide "
                    "dinero de vuelta por un cobro incorrecto / ajuste de precio NO ligado "
                    "a devolver mercancía. Devolver producto físico → returns (el reembolso "
                    "va tras recibir el artículo). Dañado/no recibido → complaint. Cancelar "
                    "pedido no enviado → order_change."
                ),
                "examples": [
                    "¿cuándo me llega el reembolso?",
                    "me han cobrado dos veces",
                    "no me aplicaron el descuento, quiero la diferencia",
                ],
            },
            "allowed_skills": [
                "shopify.get_order_status",
                "shopify.get_order_by_email",
                "shopify.get_shop_policies",
                "shopify.refund_partial",
            ],
            "required_data": [
                "Identificador del pedido (nº o email)",
                "Motivo del reembolso y artículo/importe afectado",
            ],
            "guardrails": [
                "El reembolso por una DEVOLUCIÓN se emite tras recibir y verificar el producto: eso es returns, no aquí. No prometas reembolso inmediato por devolver algo.",
                "refund_partial solo para casos DIRECTOS sin devolución (sobrecobro, ajuste de precio acordado). Importe y moneda salen del pedido, nunca inventados.",
                "El reembolso queda pendiente de aprobación; no afirmes que ya se hizo.",
                "Plazos/condiciones de reembolso: respóndelos con la política REAL (KB inyectada / tenant_facts / get_shop_policies). No escales una pregunta de política si el dato está en esas fuentes; escala solo si falta en todas.",
                "Daño/no-recibido/disputa/importe alto/reembolso total → escala, no lo fuerces.",
                "Comprueba que no exista ya un reembolso para ese pedido antes de iniciar otro.",
            ],
            "max_tool_iterations": 5,
            "confidence_threshold": 0.78,
            "require_supervision": True,
            "escalation_triggers": [
                "Importe alto o reembolso total",
                "Disputa, chargeback o sospecha de fraude",
                "El cliente alega cobro duplicado",
            ],
        },
        "body": (
            "## Procedimiento: reembolso\n"
            "Objetivo: estado de reembolsos + reembolsos DIRECTOS sin devolución; el resto, escalar o reconducir.\n\n"
            "1. ¿Pregunta GENERAL por plazos/condiciones de reembolso (sin un pedido concreto)? → responde con la\n"
            "   política real: KB inyectada / tenant_facts / get_shop_policies. Si ninguna lo cubre, dilo y escala.\n"
            "2. ¿Pregunta por el ESTADO de un reembolso? → get_order_status (revisa los refunds del pedido) e informa.\n"
            "3. ¿Sobrecobro o ajuste de precio claro y dentro de política (SIN devolver producto)? → refund_partial\n"
            "   (order_id, amount, currency del pedido). Queda en aprobación; informa.\n"
            "4. ¿Quiere el dinero por DEVOLVER un producto? → es returns: el reembolso se emite tras recibir y\n"
            "   verificar el artículo. Reconduce (el grafo reclasifica).\n"
            "5. Daño/no-recibido → complaint. Disputa, importe alto o reembolso total → escala con resumen."
        ),
    },
    {
        "slug": "product_info",
        "frontmatter": {
            "name": "Información de producto",
            "slug": "product_info",
            "workspace": CANONICAL_WORKSPACE,
            "triggers": {
                "description": (
                    "Dudas pre-compra sobre un producto: disponibilidad/stock, tallas, "
                    "materiales, specs, precio. NO es estado de pedido ni devolución."
                ),
                "examples": [
                    "¿tenéis esta camiseta en talla M?",
                    "¿de qué material está hecho?",
                    "¿cuándo reponéis stock?",
                ],
            },
            "allowed_skills": [
                "shopify.get_product_info",
                "shopify.get_shop_policies",
            ],
            "required_data": [
                "Qué producto: nombre, variante o SKU",
            ],
            "guardrails": [
                "No inventes specs, stock ni precios: usa get_product_info. El stock refleja lo que devuelve la skill.",
                "Si no identificas el producto, pide nombre/variante antes de responder.",
            ],
            "max_tool_iterations": 3,
            "confidence_threshold": 0.60,
            "require_supervision": False,
            "escalation_triggers": [
                "El producto no existe en el catálogo",
                "Pregunta técnica que la ficha no cubre",
            ],
        },
        "body": (
            "## Procedimiento: información de producto\n"
            "Objetivo: responder dudas de producto con la ficha real, sin inventar.\n\n"
            "1. Identifica el producto (nombre/variante/SKU). Si es ambiguo, pídelo.\n"
            "2. get_product_info para disponibilidad, specs, precio.\n"
            "3. Responde solo con lo que devuelve la skill; el stock puede cambiar.\n"
            "4. Garantía/condiciones → política real: KB inyectada / tenant_facts / get_shop_policies.\n"
            "5. Si no existe o la ficha no cubre la duda → dilo y escala."
        ),
    },
    {
        "slug": "order_change",
        "frontmatter": {
            "name": "Cambio o cancelación de pedido",
            "slug": "order_change",
            "workspace": CANONICAL_WORKSPACE,
            "triggers": {
                "description": (
                    "El cliente quiere MODIFICAR un pedido ya hecho que aún no se ha "
                    "enviado: cambiar la dirección de envío o cancelarlo. NO es devolver "
                    "(returns) ni reembolso de algo ya entregado (refunds)."
                ),
                "examples": [
                    "quiero cambiar la dirección de envío",
                    "cancela mi pedido por favor",
                    "puse mal el código postal",
                ],
            },
            "allowed_skills": [
                "shopify.get_order_status",
                "shopify.update_shipping_address",
                "shopify.cancel_order",
            ],
            "required_data": [
                "Identificador del pedido",
                "Para dirección: la dirección nueva completa (calle, localidad, código postal); la provincia y el país se deducen del CP/tienda y se confirman, no hace falta pedirlos por separado",
            ],
            "guardrails": [
                "Solo cambias dirección o cancelas si el pedido NO se ha enviado (unfulfilled). Si ya se envió → no es posible; explícalo y ofrece la vía de devolución / escala.",
                "Para cambio de dirección necesitas la dirección completa, pero no la pidas campo por campo a ciegas: con el código postal deduce la provincia (y la localidad solo si el CP la identifica sin ambigüedad). Pide al cliente únicamente lo que falte; si dudas, pregunta y nunca inventes.",
                "NO envíes el campo `country` a update_shipping_address en un cambio doméstico: por defecto se conserva el país del pedido. Pásalo solo si el cliente cambia de país de envío explícitamente.",
                "Antes de update_shipping_address, lee al cliente la dirección completa parseada (calle, ciudad, provincia, país, código postal) y espera su confirmación: un error de transcripción no debe llegar a aprobación sin validarlo con el cliente.",
                "Cambio y cancelación quedan pendientes de aprobación; informa que está en proceso.",
                "No canceles ni modifiques sin petición explícita del cliente.",
                "Una vez que el cambio o la cancelación ya quedó en aprobación o se aplicó en esta conversación, NO vuelvas a llamar la skill ante agradecimientos, confirmaciones o mensajes de cortesía del cliente: responde con cordialidad y cierra. Ejecuta de nuevo solo si el cliente pide explícitamente una acción nueva o distinta.",
            ],
            "max_tool_iterations": 5,
            "confidence_threshold": 0.72,
            "require_supervision": True,
            "escalation_triggers": [
                "El pedido ya fue enviado/fulfilled",
                "Pago en disputa",
                "El cliente pide modificar artículos o cantidades (no soportado)",
            ],
        },
        "body": (
            "## Procedimiento: cambio o cancelación de pedido\n"
            "Objetivo: modificar (dirección) o cancelar un pedido AÚN NO enviado, con aprobación.\n\n"
            "1. Localiza el pedido (get_order_status) y comprueba el estado de fulfillment.\n"
            "2. Si ya está enviado (fulfilled) → no se puede cambiar/cancelar; explícalo y reconduce a devolución o escala.\n"
            "3. Cambio de dirección (unfulfilled): reúne la dirección nueva pidiendo solo lo necesario (calle, localidad y código postal); deduce la provincia del CP en vez de pedirla por separado. El país se conserva del pedido automáticamente: NO lo pidas ni lo envíes salvo cambio internacional explícito. Antes de seguir, lee al cliente la dirección completa tal como la registraste y pide que confirme que es correcta. Solo con su confirmación → update_shipping_address (order_id + dirección). Pendiente de aprobación; informa.\n"
            "4. Cancelación (unfulfilled): confirma la intención → cancel_order (order_id). Pendiente de aprobación; informa.\n"
            "5. Tras dejar la acción en aprobación (o aplicada), si el cliente solo agradece o se despide, responde con cordialidad y cierra — NO vuelvas a llamar la skill. Repite la acción únicamente si pide un cambio nuevo o distinto.\n"
            "6. Modificar artículos/cantidades no está soportado → escala."
        ),
    },
    {
        "slug": "complaint",
        "frontmatter": {
            "name": "Queja / incidencia",
            "slug": "complaint",
            "workspace": CANONICAL_WORKSPACE,
            "triggers": {
                "description": (
                    "Incidencia o queja seria: producto dañado/defectuoso, pedido no "
                    "recibido pese a figurar entregado, cliente muy enfadado o amenaza "
                    "legal. Prioridad: acusar recibo con empatía y escalar a una persona."
                ),
                "examples": [
                    "el producto llegó roto",
                    "pone entregado pero no he recibido nada",
                    "esto es inaceptable, voy a reclamar",
                ],
            },
            "allowed_skills": [
                "shopify.get_order_status",
                "shopify.get_customer_history",
                "shopify.tag_order",
                "shopify.add_order_note",
            ],
            "required_data": [],
            "guardrails": [
                "No prometas compensación, reembolso ni reenvío: eso lo decide el equipo humano.",
                "Mantén tono empático y calmado, incluso ante agresividad o amenazas.",
                "No admitas culpa legal ni hagas declaraciones que comprometan a la empresa.",
                "Recoge contexto y escala con un resumen claro; no intentes resolver tú la incidencia.",
            ],
            "max_tool_iterations": 4,
            "confidence_threshold": 0.70,
            "require_supervision": True,
            "escalation_triggers": [
                "Toda queja seria (dañado, no recibido, amenaza legal) → escala tras acusar recibo",
            ],
        },
        "body": (
            "## Procedimiento: queja / incidencia\n"
            "Objetivo: contener con empatía y escalar a una persona con contexto. NO resolver tú.\n\n"
            "1. Reconoce el problema con empatía, sin prometer soluciones concretas.\n"
            "2. Recoge contexto: get_order_status (si hay pedido) y get_customer_history.\n"
            "3. Marca el pedido como incidencia con tag_order y deja un add_order_note con el resumen para el equipo.\n"
            "4. Dile al cliente que lo estás escalando a una persona que lo revisará en breve.\n"
            "5. Escala con resumen: pedido, naturaleza de la incidencia y contexto relevante."
        ),
    },
    {
        "slug": "default",
        "frontmatter": {
            "name": "Atención general",
            "slug": "default",
            "workspace": CANONICAL_WORKSPACE,
            "triggers": {
                "description": (
                    "Catch-all para mensajes que no encajan claramente en otro "
                    "procedimiento o cuando la confianza del clasificador es baja. Solo "
                    "lectura: informar y, si hace falta una acción, escalar."
                ),
                "examples": [
                    "hola, tengo una duda",
                    "¿me podéis ayudar?",
                ],
            },
            "allowed_skills": [
                "shopify.get_shop_policies",
                "shopify.get_product_info",
                "shopify.get_order_status",
                "shopify.get_customer_history",
            ],
            "required_data": [],
            "guardrails": [
                "No inventes: si no está en la KB, las políticas o el output de una skill, dilo y escala.",
                "No tienes herramientas de escritura. Si el cliente pide una acción (cancelar, reembolsar, cambiar, devolver), recoge contexto y escala — o el grafo reclasificará al AOP adecuado.",
            ],
            "max_tool_iterations": 4,
            "confidence_threshold": 0.60,
            "require_supervision": False,
            "escalation_triggers": [
                "No hay información confiable para responder",
                "El cliente pide una acción que requiere herramientas no disponibles aquí",
            ],
        },
        "body": (
            "## Procedimiento: atención general\n"
            "Objetivo: ayudar con información de solo lectura; ante acciones, escalar.\n\n"
            "1. Entiende qué necesita. Si es info (envíos, garantías, producto, estado de pedido) → usa la skill L1 que corresponda.\n"
            "2. Responde solo con datos reales (skill/KB). Si no los tienes → dilo y escala.\n"
            "3. No tienes herramientas de escritura: si pide una acción, recoge el contexto y escala (o el grafo reclasifica).\n"
            "4. Sé honesto sobre lo que sabes y lo que no."
        ),
    },
]


# ─── Permisos de herramientas por defecto ──────────────────────────────────────
# execute_skill rechaza CUALQUIER skill sin row is_enabled=True (incluidas L1).
# Postura canónica: L1/L2 autónomos; L3 enabled + human_approval_required=True.
# super_admin gradúa un L3 a automático (human_approval_required=False) por cliente.

CANONICAL_TOOL_PERMISSIONS: list[dict[str, Any]] = [
    # L1 — lectura, autónomas
    {"skill_slug": "shopify.get_order_status", "is_enabled": True, "human_approval_required": False},
    {"skill_slug": "shopify.get_order_by_email", "is_enabled": True, "human_approval_required": False},
    {"skill_slug": "shopify.get_product_info", "is_enabled": True, "human_approval_required": False},
    {"skill_slug": "shopify.get_shop_policies", "is_enabled": True, "human_approval_required": False},
    {"skill_slug": "shopify.get_customer_history", "is_enabled": True, "human_approval_required": False},
    # L2 — escritura reversible, autónomas
    {"skill_slug": "shopify.add_order_note", "is_enabled": True, "human_approval_required": False},
    {"skill_slug": "shopify.tag_order", "is_enabled": True, "human_approval_required": False},
    # L3 — destructivas, enabled pero con aprobación humana por defecto
    {"skill_slug": "shopify.start_return", "is_enabled": True, "human_approval_required": True},
    {"skill_slug": "shopify.refund_partial", "is_enabled": True, "human_approval_required": True},
    {"skill_slug": "shopify.cancel_order", "is_enabled": True, "human_approval_required": True},
    {"skill_slug": "shopify.update_shipping_address", "is_enabled": True, "human_approval_required": True},
]


# ─── Provisioning ──────────────────────────────────────────────────────────────


def _build_raw_source(frontmatter: dict[str, Any], body: str) -> str:
    """Construye el source editable '---\\nYAML\\n---\\nbody' que round-trippea con
    routers/aops.py::_parse_raw_source, para que el editor del dashboard lo abra."""
    fm_yaml = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).strip()
    return f"---\n{fm_yaml}\n---\n{body.strip()}\n"


async def provision_canonical_aops(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    *,
    created_by: UUID | None = None,
    update_existing: bool = False,
) -> dict[str, int]:
    """Siembra los 8 AOPs canónicos + permisos default para `tenant_id`. Idempotente.

    No abre transacción propia: el caller decide la atomicidad. `provision_tenant` lo
    envuelve en su transacción (todo o nada). La conexión debe tener privilegios
    (bootstrap_connection) o ser el tenant_scope del propio tenant.

    - AOP existente (mismo slug) → se salta, salvo `update_existing=True` (crea versión nueva).
    - Permisos siempre se hacen upsert (idempotente).
    """
    created = updated = skipped = 0
    for aop in CANONICAL_AOPS:
        slug = aop["slug"]
        frontmatter = aop["frontmatter"]
        body = aop["body"]
        raw_source = _build_raw_source(frontmatter, body)

        existing = await get_aop_by_slug(conn, tenant_id, slug, CANONICAL_WORKSPACE)
        if existing is not None:
            if update_existing:
                await save_aop_version(
                    conn,
                    tenant_id=tenant_id,
                    aop_id=existing.id,
                    yaml_frontmatter=frontmatter,
                    body_markdown=body,
                    raw_source=raw_source,
                    created_by=created_by,
                )
                updated += 1
            else:
                skipped += 1
            continue

        try:
            await create_aop(
                conn,
                tenant_id=tenant_id,
                slug=slug,
                workspace=CANONICAL_WORKSPACE,
                yaml_frontmatter=frontmatter,
                body_markdown=body,
                raw_source=raw_source,
                created_by=created_by,
            )
            created += 1
        except asyncpg.UniqueViolationError:
            # Carrera: otro proceso lo creó entre el SELECT y el INSERT.
            skipped += 1

    for perm in CANONICAL_TOOL_PERMISSIONS:
        await upsert_tool_permission(
            conn,
            tenant_id=tenant_id,
            skill_slug=perm["skill_slug"],
            is_enabled=perm["is_enabled"],
            human_approval_required=perm["human_approval_required"],
            enabled_by=created_by,
        )

    logger.info(
        "provision_canonical_aops tenant=%s created=%d updated=%d skipped=%d perms=%d",
        tenant_id,
        created,
        updated,
        skipped,
        len(CANONICAL_TOOL_PERMISSIONS),
    )
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "tool_permissions": len(CANONICAL_TOOL_PERMISSIONS),
    }
