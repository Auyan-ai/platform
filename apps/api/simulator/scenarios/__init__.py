"""Package de scenarios del simulador.

`seed_scenarios(conn, tenant_id)` inserta los scenarios base que le falten a un tenant.
Es idempotente: si el scenario ya existe (mismo `name`), no lo duplica.

`sync_scenario_from_code` deja un scenario base igual que en el código justo antes de
correrlo. Lo llama el runner, así que vale para `run_simulator` y para el panel.
"""

from __future__ import annotations

import logging
from uuid import UUID

import asyncpg
from apps.api.db.models import SimulationScenario
from apps.api.db.queries import (
    get_user_profile_by_name,
    insert_simulation_scenario,
    insert_user_profile,
    update_simulation_scenario,
    update_user_profile,
)
from apps.api.simulator.scenarios.consulta_envio import SCENARIOS as CE_SCENARIOS
from apps.api.simulator.scenarios.default import SCENARIOS as DE_SCENARIOS
from apps.api.simulator.scenarios.edge_cases import SCENARIOS as EX_SCENARIOS
from apps.api.simulator.scenarios.identity import SCENARIOS as ID_SCENARIOS
from apps.api.simulator.scenarios.language import SCENARIOS as LG_SCENARIOS
from apps.api.simulator.scenarios.orders import SCENARIOS as OR_SCENARIOS
from apps.api.simulator.scenarios.profiles import PERSONAS
from apps.api.simulator.scenarios.returns import SCENARIOS as RE_SCENARIOS

logger = logging.getLogger(__name__)

ALL_SCENARIOS = (
    CE_SCENARIOS
    + RE_SCENARIOS
    + DE_SCENARIOS
    + EX_SCENARIOS
    + ID_SCENARIOS
    + OR_SCENARIOS
    + LG_SCENARIOS
)


_BY_NAME = {sc["name"]: sc for sc in ALL_SCENARIOS}


def capabilities_by_name() -> dict[str, list[str]]:
    """Códigos del catálogo de capacidades que cubre cada escenario, por nombre.

    Viven en el código (`capabilities` de cada escenario) y no en la DB: el catálogo
    cambia con el código, no con los datos del tenant.
    """
    return {sc["name"]: list(sc.get("capabilities", [])) for sc in ALL_SCENARIOS}


async def sync_scenario_from_code(
    conn: asyncpg.Connection, tenant_id: UUID, scenario: SimulationScenario
) -> SimulationScenario:
    """El scenario base (mismo `name` que en el código) con sus campos y su profile como
    en el código. Las fechas de los fixtures (`days_ago`) se calculan al importar el
    módulo, así que una fila sembrada otro día tendría plazos caducados. Un scenario
    creado desde el panel, sin equivalente en el código, vuelve tal cual."""
    sc = _BY_NAME.get(scenario.name)
    if sc is None:
        return scenario
    await update_user_profile(
        conn,
        tenant_id=tenant_id,
        profile_id=scenario.user_profile_id,
        persona=PERSONAS[sc["profile"]],
        goal=sc["goal"],
        initial_message=sc["initial_message"],
        language="es",
    )
    updated = await update_simulation_scenario(
        conn,
        tenant_id=tenant_id,
        scenario_id=scenario.id,
        aop_slug=sc["aop_slug"],
        expected_outcome=sc["expected_outcome"],
        description=sc.get("description"),
        mock_fixtures=sc.get("mock_fixtures", {}),
        assertions=sc.get("assertions", {}),
        max_turns=sc.get("max_turns", 8),
    )
    logger.info("sim_seed_scenario synced id=%s tenant=%s", sc["id"], tenant_id)
    return updated or scenario


async def seed_scenarios(conn: asyncpg.Connection, tenant_id: UUID) -> dict[str, int]:
    """Inserta profiles y scenarios base que falten en el tenant. Idempotente por nombre.

    No actualiza los que ya existen: eso lo hace `sync_scenario_from_code` antes de cada
    corrida. Retorna {"profiles": N, "scenarios": N} con los counts.
    """
    profiles_created = 0
    scenarios_created = 0

    # 1. Upsert profiles por nombre (idempotente)
    profile_map: dict[str, UUID] = {}
    for persona_key, persona_data in PERSONAS.items():
        existing = await get_user_profile_by_name(conn, tenant_id, f"[Base] {persona_key}")
        if existing:
            profile_map[persona_key] = existing.id
            continue

        profile = await insert_user_profile(
            conn,
            tenant_id=tenant_id,
            name=f"[Base] {persona_key}",
            persona=persona_data,
            goal=f"Perfil base — {persona_key}",
            initial_message="Hola",
            language="es",
        )
        profile_map[persona_key] = profile.id
        profiles_created += 1
        logger.info("sim_seed_profile created name=%s tenant=%s", profile.name, tenant_id)

    # 2. Insertar scenarios por nombre (idempotente)
    rows = await conn.fetch(
        "SELECT name FROM simulation_scenarios WHERE tenant_id = $1 AND deleted_at IS NULL",
        tenant_id,
    )
    existing_names = {r["name"] for r in rows}

    for sc in ALL_SCENARIOS:
        if sc["name"] in existing_names:
            continue

        profile_key = sc["profile"]
        if profile_key not in profile_map:
            logger.warning(
                "sim_seed_missing_profile scenario=%s profile=%s", sc["id"], profile_key
            )
            continue

        # Para el seed, el initial_message de la persona viene del scenario
        # Actualizamos el profile con el goal del primer scenario que lo use
        # (cada scenario tiene su propio goal/initial_message diferente).
        # En seed, creamos un profile POR SCENARIO que tiene el goal específico.
        profile_name = f"[Sim] {sc['id']} — {sc['profile']}"
        existing_sc_profile = await get_user_profile_by_name(conn, tenant_id, profile_name)
        if existing_sc_profile:
            sc_profile_id = existing_sc_profile.id
        else:
            sc_profile = await insert_user_profile(
                conn,
                tenant_id=tenant_id,
                name=profile_name,
                persona=PERSONAS[profile_key],
                goal=sc["goal"],
                initial_message=sc["initial_message"],
                language="es",
            )
            sc_profile_id = sc_profile.id
            profiles_created += 1

        await insert_simulation_scenario(
            conn,
            tenant_id=tenant_id,
            name=sc["name"],
            description=sc.get("description"),
            aop_slug=sc["aop_slug"],
            user_profile_id=sc_profile_id,
            expected_outcome=sc["expected_outcome"],
            mock_fixtures=sc.get("mock_fixtures", {}),
            assertions=sc.get("assertions", {}),
            max_turns=sc.get("max_turns", 8),
        )
        scenarios_created += 1
        logger.info("sim_seed_scenario created id=%s tenant=%s", sc["id"], tenant_id)

    return {"profiles": profiles_created, "scenarios": scenarios_created}
