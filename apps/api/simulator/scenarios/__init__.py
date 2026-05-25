"""Package de scenarios del simulador.

`seed_scenarios(conn, tenant_id)` inserta o actualiza los 25 scenarios base
para un tenant dado. Es idempotente: si el scenario ya existe (mismo `name`),
no lo duplica.
"""

from __future__ import annotations

import logging
from uuid import UUID

import asyncpg
from apps.api.db.queries import (
    get_scenario_by_name,
    get_user_profile_by_name,
    insert_simulation_scenario,
    insert_user_profile,
    update_simulation_scenario,
)
from apps.api.simulator.scenarios.consulta_envio import SCENARIOS as CE_SCENARIOS
from apps.api.simulator.scenarios.default import SCENARIOS as DE_SCENARIOS
from apps.api.simulator.scenarios.edge_cases import SCENARIOS as EX_SCENARIOS
from apps.api.simulator.scenarios.profiles import PERSONAS
from apps.api.simulator.scenarios.returns import SCENARIOS as RE_SCENARIOS

logger = logging.getLogger(__name__)

ALL_SCENARIOS = CE_SCENARIOS + RE_SCENARIOS + DE_SCENARIOS + EX_SCENARIOS


async def seed_scenarios(
    conn: asyncpg.Connection, tenant_id: UUID, *, reseed: bool = False
) -> dict[str, int]:
    """Inserta profiles y scenarios base para el tenant. Idempotente por nombre.

    Con reseed=True, actualiza los campos mutables (mock_fixtures, assertions,
    expected_outcome, description, aop_slug, max_turns) de los scenarios que ya
    existen, en vez de saltarlos. El profile/initial_message no se toca.

    Retorna {"profiles": N, "scenarios": N, "updated": N} con los counts.
    """
    profiles_created = 0
    scenarios_created = 0
    scenarios_updated = 0

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

    # 2. Upsert scenarios por nombre (idempotente)
    rows = await conn.fetch(
        "SELECT name FROM simulation_scenarios WHERE tenant_id = $1 AND deleted_at IS NULL",
        tenant_id,
    )
    existing_names = {r["name"] for r in rows}

    for sc in ALL_SCENARIOS:
        if sc["name"] in existing_names:
            if reseed:
                existing_sc = await get_scenario_by_name(conn, tenant_id, sc["name"])
                if existing_sc is not None:
                    await update_simulation_scenario(
                        conn,
                        tenant_id=tenant_id,
                        scenario_id=existing_sc.id,
                        aop_slug=sc["aop_slug"],
                        expected_outcome=sc["expected_outcome"],
                        description=sc.get("description"),
                        mock_fixtures=sc.get("mock_fixtures", {}),
                        assertions=sc.get("assertions", {}),
                        max_turns=sc.get("max_turns", 8),
                    )
                    scenarios_updated += 1
                    logger.info("sim_seed_scenario updated id=%s tenant=%s", sc["id"], tenant_id)
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

    return {
        "profiles": profiles_created,
        "scenarios": scenarios_created,
        "updated": scenarios_updated,
    }
