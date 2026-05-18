"""Puebla la KB de un tenant con contenido fantasioso de Lunaria para pruebas de anti-alucinación.

El contenido usa datos específicos e inventados (precios impares, tiempos en "ciclos lunares",
nombres de productos únicos) para que sea obvio cuando el agente alucina en lugar de usar el KB.

Regla de oro para detectar alucinación:
  - Si el agente dice "30 días" → alucinó (la política real son 7 lunas llenas = 49 días)
  - Si el agente dice "Envío gratis" → alucinó (el mínimo real son €137)
  - Si menciona un producto que no existe → alucinó

Uso:
    cd apps/api
    poetry run python -m scripts.seed_kb
    poetry run python -m scripts.seed_kb --tenant lunaria --dry-run
    poetry run python -m scripts.seed_kb --clear   # borra KB del tenant antes de insertar
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import openai
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_FILE)

# ---------------------------------------------------------------------------
# Contenido KB fantasioso de Lunaria
# Cada documento es una lista de chunks. Chunk = texto corto (<300 tokens).
# Valores deliberadamente impares y únicos para detectar alucinaciones.
# ---------------------------------------------------------------------------

DOCUMENTS: list[dict] = [
    {
        "title": "Política de Devoluciones — Lunaria",
        "source": "policy/devoluciones",
        "chunks": [
            (
                "En Lunaria aceptamos devoluciones durante los 7 ciclos de luna llena "
                "posteriores a la recepción del pedido (equivalente a 49 días naturales). "
                "Después de este plazo no se aceptan devoluciones bajo ninguna circunstancia. "
                "El plazo de 49 días es inamovible e improrrogable."
            ),
            (
                "Para iniciar una devolución el producto debe estar en su Caja Lunar Sellada original, "
                "con todos los amuletos de protección incluidos (piedra de obsidiana + cinta de terciopelo índigo). "
                "Productos sin la Caja Lunar Sellada no son elegibles para devolución. "
                "La ausencia de cualquiera de los amuletos reduce el reembolso en €23 por pieza faltante."
            ),
            (
                "El reembolso se realiza exclusivamente mediante Crédito Estelar en la cuenta Lunaria del cliente. "
                "Reembolsos en efectivo o tarjeta no están disponibles. "
                "El Crédito Estelar expira a los 3 años desde su emisión. "
                "Excepción: defectos de fabricación — en ese caso sí se reembolsa a la tarjeta original en €."
            ),
            (
                "Artículos de la Colección Eclipse Negro y joyería personalizada (grabados o piedras seleccionadas) "
                "son VENTAS FINALES. No aplica devolución ni cambio bajo ningún concepto. "
                "Esta excepción no tiene ninguna excepción adicional."
            ),
        ],
    },
    {
        "title": "Catálogo de Colecciones — Lunaria",
        "source": "catalog/colecciones",
        "chunks": [
            (
                "Colección Fases Lunares: anillos que cambian de apariencia según el ángulo de luz. "
                "Anillo Cuarto Creciente (plata 925 + labradorita) — €137. "
                "Anillo Luna Llena (plata 925 + piedra de luna) — €189. "
                "Anillo Cuarto Menguante (plata 925 + obsidiana) — €137. "
                "Anillo Luna Nueva (oro negro 18k + diamante negro) — €743."
            ),
            (
                "Colección Constelaciones Perdidas: collares con mapas estelares de constelaciones "
                "que ya no son visibles desde Europa. "
                "Collar Ophiuchus Dorado (oro 14k + 13 granates) — €311. "
                "Collar Argo Náutica (plata oxidada + zafiro estelar) — €289. "
                "Colgante Sextante (bronce + meteorito auténtico de 1.3g) — €521."
            ),
            (
                "Colección Eclipse Negro: joyería edición limitada disponible solo durante eclipses solares. "
                "El siguiente lanzamiento está previsto para el próximo eclipse solar visible en España. "
                "Pulsera Eclipse Total (titanio negro + ónix rayado) — €433. "
                "Pendientes Umbra (plata negra + turmalina negra, par) — €267. "
                "Todos los artículos Eclipse Negro son venta final — sin devoluciones."
            ),
            (
                "Colección Guardianas: exclusiva para miembros del programa Guardianas de la Luna. "
                "Anillo Guardiana Eterna (oro rosa 18k + rubí estelar 0.8ct) — €1.107 (€887 para Guardianas). "
                "Diadema de las Mareas (plata 925 + 7 perlas de Tahití) — €893 (€714 para Guardianas). "
                "No disponibles para compra pública."
            ),
        ],
    },
    {
        "title": "Política de Envíos — Lunaria",
        "source": "policy/envios",
        "chunks": [
            (
                "Lunaria opera con tres modalidades de envío: "
                "1. Constelación Express — entrega en 2 a 4 días hábiles — €9.50. "
                "2. Tránsito Lunar — entrega en 7 a 9 días hábiles — €4.20. "
                "3. Viaje Estelar (Europa fuera de España) — entrega en 14 a 21 días hábiles — €17.80. "
                "El envío gratuito aplica a partir de €137 en pedidos nacionales (España)."
            ),
            (
                "El tracking de pedidos Lunaria usa el sistema interno de seguimiento Órbita. "
                "Cada pedido tiene un código Órbita de 9 caracteres (formato LN-XXXXXXX). "
                "El código Órbita se envía por email entre 2 y 6 horas después de la confirmación del pedido. "
                "El tracking Órbita se actualiza cada 4 horas, no en tiempo real."
            ),
            (
                "Países con envío disponible: todos los países de la Unión Europea más Reino Unido, Suiza y Noruega. "
                "Lunaria NO envía a América, Asia, África ni Oceanía. "
                "No existe ningún servicio de recogida en tienda — Lunaria es 100% online. "
                "Intentos de entrega fallidos: el mensajero intenta 2 veces. Al tercer intento el paquete vuelve a Lunaria "
                "y el cliente paga €7.50 de reenvío."
            ),
            (
                "Pedidos realizados antes de las 14:00 (hora de Madrid) en días laborables se procesan el mismo día. "
                "Pedidos después de las 14:00 o en fin de semana/festivos se procesan el siguiente día laborable. "
                "En temporada alta (noviembre y diciembre) los tiempos de procesamiento pueden extenderse 48 horas adicionales."
            ),
        ],
    },
    {
        "title": "Programa Guardianas de la Luna — Lunaria VIP",
        "source": "loyalty/guardianas",
        "chunks": [
            (
                "Guardianas de la Luna es el programa de fidelización exclusivo de Lunaria. "
                "La membresía anual tiene un coste de €89/año o €8.90/mes. "
                "Beneficios: 15% de descuento en toda la tienda (no acumulable con otras ofertas), "
                "acceso anticipado 72 horas a nuevas colecciones, y acceso a la Colección Guardianas."
            ),
            (
                "Niveles del programa Guardianas: "
                "Nivel Creciente — primer año de membresía. "
                "Nivel Llena — a partir de 2 años consecutivos O €600 en compras durante el año. "
                "Nivel Eclipse — a partir de 4 años consecutivos O €1.500 en compras durante el año. "
                "El nivel Eclipse incluye envío Constelación Express gratuito en todos los pedidos."
            ),
            (
                "Cancelar la membresía Guardianas: se puede cancelar en cualquier momento. "
                "Si se cancela antes de cumplir el año, no hay reembolso de la cuota anual. "
                "Al cancelar se pierde el acceso a la Colección Guardianas y el descuento del 15% "
                "inmediatamente, pero se mantiene el Crédito Estelar acumulado."
            ),
        ],
    },
    {
        "title": "Preguntas Frecuentes — Lunaria",
        "source": "faq/general",
        "chunks": [
            (
                "¿Lunaria tiene tienda física? No. Lunaria es exclusivamente online. "
                "No existe ningún punto de venta físico ni pop-up store permanente. "
                "Ocasionalmente Lunaria participa en ferias de joyería en Madrid y Barcelona, "
                "pero no se puede comprar ni recoger pedidos en esos eventos."
            ),
            (
                "¿Los materiales son certificados? Sí. "
                "Toda la plata es 925 con certificado SGS. "
                "El oro 14k y 18k tiene certificado del Consejo Mundial del Oro. "
                "Las piedras preciosas vienen con certificado GIA si tienen valor superior a €200. "
                "Los meteoritos incluyen certificado de autenticidad del Instituto Meteorítico de Viena."
            ),
            (
                "¿Lunaria hace joyería personalizada? Sí, con restricciones. "
                "Solo se aceptan personalizaciones de texto (grabados) o selección de piedra dentro del catálogo. "
                "No se hacen diseños a medida. "
                "Los pedidos personalizados tardan entre 11 y 17 días laborables adicionales. "
                "Precio de personalización: €27 por grabado, €0 por selección de piedra del catálogo."
            ),
            (
                "¿Cómo funciona el Crédito Estelar? "
                "El Crédito Estelar es la moneda interna de Lunaria usada para reembolsos. "
                "1 Crédito Estelar = €1 exacto. "
                "Se puede usar en cualquier compra futura sin mínimo. "
                "No se puede convertir a dinero. Expira a los 3 años. "
                "Se acumula también a través del programa Guardianas (2 Créditos Estelares por cada €100 gastados)."
            ),
            (
                "¿Qué pasa si mi pedido llega dañado? "
                "Tienes 48 horas desde la recepción para reportar el daño con fotos al email "
                "lunas@lunaria.es con asunto 'Daño en pedido LN-XXXXXXX'. "
                "Pasadas 48 horas Lunaria no puede tramitar la reclamación. "
                "En caso de daño confirmado, Lunaria envía el producto de reemplazo sin coste "
                "en modalidad Constelación Express, sin necesidad de devolver el dañado."
            ),
        ],
    },
]


def _vec_to_pg(embedding: list[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


async def _get_tenant_id(conn: asyncpg.Connection, slug: str) -> str:
    row = await conn.fetchrow(
        "SELECT id FROM tenants WHERE slug = $1 AND deleted_at IS NULL", slug
    )
    if row is None:
        raise SystemExit(f"Tenant '{slug}' no encontrado.")
    return str(row["id"])


async def _clear_kb(conn: asyncpg.Connection, tenant_id: str) -> int:
    result = await conn.execute(
        "UPDATE knowledge_base_documents SET deleted_at = now() "
        "WHERE tenant_id = $1::uuid AND deleted_at IS NULL",
        tenant_id,
    )
    count = int(result.split()[-1])
    return count


async def run(tenant_slug: str, dry_run: bool, clear: bool) -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not database_url:
        raise SystemExit("DATABASE_URL no está en .env")
    if not openai_api_key:
        raise SystemExit("OPENAI_API_KEY no está en .env")

    oai = openai.AsyncOpenAI(api_key=openai_api_key, timeout=30.0)

    conn: asyncpg.Connection = await asyncpg.connect(database_url)
    try:
        tenant_id = await _get_tenant_id(conn, tenant_slug)
        print(f"Tenant: {tenant_slug} ({tenant_id})")

        if clear:
            n = await _clear_kb(conn, tenant_id)
            print(f"  → {n} documentos marcados como deleted_at (soft delete).")

        total_chunks = 0
        for doc in DOCUMENTS:
            print(f"\nDocumento: {doc['title']}")
            chunks = doc["chunks"]

            # Embeddings
            print(f"  Generando {len(chunks)} embeddings...", end=" ", flush=True)
            resp = await oai.embeddings.create(
                model="text-embedding-3-small",
                input=chunks,
            )
            embeddings = [item.embedding for item in resp.data]
            print("OK")

            if dry_run:
                print(f"  [dry-run] Se insertarían {len(chunks)} chunks.")
                total_chunks += len(chunks)
                continue

            # Insertar documento
            doc_id = str(uuid4())
            await conn.execute(
                """
                INSERT INTO knowledge_base_documents (id, tenant_id, title, source, content)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5)
                """,
                doc_id,
                tenant_id,
                doc["title"],
                doc["source"],
                "\n\n".join(chunks),
            )

            # Insertar chunks
            chunk_rows = [
                (
                    str(uuid4()),
                    tenant_id,
                    doc_id,
                    i,
                    chunks[i],
                    _vec_to_pg(embeddings[i]),
                    len(chunks[i].split()),
                )
                for i in range(len(chunks))
            ]
            await conn.executemany(
                """
                INSERT INTO knowledge_base_chunks
                  (id, tenant_id, document_id, chunk_index, content, embedding, token_count)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6::vector, $7)
                """,
                chunk_rows,
            )
            print(f"  ✓ {len(chunks)} chunks insertados (doc_id: {doc_id[:8]}...)")
            total_chunks += len(chunks)

        print(f"\n{'[dry-run] ' if dry_run else ''}Total: {total_chunks} chunks en {len(DOCUMENTS)} documentos.")
        if dry_run:
            print("No se hicieron cambios en la DB.")

    finally:
        await conn.close()
        await oai.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Puebla la KB de un tenant con contenido de prueba.")
    parser.add_argument("--tenant", default="lunaria", help="Slug del tenant (default: lunaria)")
    parser.add_argument("--dry-run", action="store_true", help="Muestra lo que haría sin escribir en DB")
    parser.add_argument("--clear", action="store_true", help="Soft-delete de todos los docs actuales antes de insertar")
    args = parser.parse_args()
    asyncio.run(run(args.tenant, args.dry_run, args.clear))


if __name__ == "__main__":
    main()
