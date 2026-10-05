"""Doctor por tenant (Sprint 2.5): parser de migraciones, checks de configuración y en vivo."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from apps.api.integrations import chatwoot, gorgias, zendesk  # noqa: F401  registran helpdesks
from apps.api.integrations.zendesk_triggers import (
    NOT_HANDOFF_CONDITION,
    reply_trigger,
    solved_trigger,
)
from apps.api.scripts.doctor import render
from apps.api.services.doctor import build_report, platform_checks
from apps.api.services.doctor.checks import (
    helpdesk_checks,
    operations_checks,
    schema_check,
    whatsapp_config_checks,
)
from apps.api.services.doctor.live import (
    interpret_account_health,
    run_live_checks,
    trigger_drift,
    zendesk_live_checks,
    zernio_live_checks,
)
from apps.api.services.doctor.schema import (
    LiveSchema,
    _Replay,
    expected_objects,
    migration_statuses,
    split_statements,
)
from apps.api.services.doctor.snapshot import (
    ActivitySnapshot,
    IntegrationSnapshot,
    TenantSnapshot,
)

from tests.conftest import TENANT_ID

API_BASE = "https://api.auyan.test"
SUBDOMAIN = "marea"
WEBHOOK_ID = "01WEBHOOK"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _integration(
    kind: str,
    provider: str,
    *,
    active: bool = True,
    primary: bool = True,
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    credentials_error: str | None = None,
) -> IntegrationSnapshot:
    return IntegrationSnapshot(
        id=uuid4(),
        kind=kind,
        provider=provider,
        is_active=active,
        is_primary=primary,
        config=config or {},
        credentials=None if credentials_error else (credentials or {}),
        credentials_error=credentials_error,
    )


def _zendesk(**config: Any) -> IntegrationSnapshot:
    return _integration(
        "helpdesk",
        "zendesk",
        config={"subdomain": SUBDOMAIN, "api_user_id": "42", **config},
        credentials={"client_id": "cid", "client_secret": "cs", "webhook_signing_secret": "s"},
    )


def _zernio(*, sandbox: bool = False, active: bool = True, **config: Any) -> IntegrationSnapshot:
    base: dict[str, Any] = {"account_id": "acc_1", "phone_number": "+34600111222"}
    if sandbox:
        base["sandbox"] = True
    else:
        base["reengagement_template"] = {"name": "auyan_reengagement", "language": "es"}
    return _integration(
        "channel",
        "zernio",
        active=active,
        config={**base, **config},
        credentials={"api_key": "zk_runtime", "webhook_secret": "whsec"},
    )


def _snapshot(*integrations: IntegrationSnapshot, activity: ActivitySnapshot | None = None):
    return TenantSnapshot(
        tenant_id=TENANT_ID,
        slug="marea-studio",
        integrations=list(integrations),
        activity=activity
        or ActivitySnapshot(last_inbound_by_channel={"zendesk": datetime.now(UTC)}),
    )


def _by_id(checks: list[Any]) -> dict[str, Any]:
    return {c.id: c for c in checks}


# ─── Parser de migraciones ────────────────────────────────────────────────────


class TestSplitStatements:
    def test_drops_comments_and_function_bodies(self) -> None:
        sql = """
        -- comentario; con punto y coma
        create table a (id int); /* bloque; */
        create function f() returns trigger language plpgsql as $$
        begin insert into x values (1); return new; end $$;
        comment on table a is 'texto; con ; puntos';
        """
        statements = split_statements(sql)
        assert statements[0] == "create table a (id int)"
        assert statements[1].startswith("create function f()")
        assert "insert into x" not in statements[1]
        assert len(statements) == 3


def _replay(sql: str, name: str = "m1.sql", replay: _Replay | None = None) -> _Replay:
    replay = replay or _Replay()
    for stmt in split_statements(sql):
        replay.apply(stmt, name)
    return replay


def _alive(replay: _Replay) -> set[tuple[str, str]]:
    return {(o.kind, o.name) for o in replay.objects if o.alive}


class TestReplay:
    def test_tables_columns_indexes(self) -> None:
        replay = _replay(
            """
            CREATE TABLE IF NOT EXISTS public.foo (id uuid primary key);
            alter table foo add column bar text, add column if not exists baz int,
              add constraint foo_bar_check check (bar <> '');
            create unique index if not exists foo_bar_idx on foo (bar);
            create index on foo (baz);
            """
        )
        assert _alive(replay) == {
            ("table", "foo"),
            ("column", "foo.bar"),
            ("column", "foo.baz"),
            ("index", "foo_bar_idx"),
        }

    def test_later_drops_and_renames_apply(self) -> None:
        replay = _replay(
            """
            create table foo (id int);
            alter table foo add column old_name text;
            create index foo_idx on foo (id);
            """,
            "m1.sql",
        )
        _replay(
            """
            alter table foo rename column old_name to new_name;
            alter index foo_idx rename to foo_id_idx;
            alter table foo rename to bar;
            """,
            "m2.sql",
            replay,
        )
        assert _alive(replay) == {
            ("table", "bar"),
            ("column", "bar.new_name"),
            ("index", "foo_id_idx"),
        }
        # El objeto sigue perteneciendo a la migración que lo creó.
        assert {o.migration for o in replay.objects if o.alive} == {"m1.sql"}

        _replay("drop table if exists bar cascade;", "m3.sql", replay)
        assert _alive(replay) == set()

    def test_enums_and_buckets(self) -> None:
        replay = _replay(
            """
            create type status as enum ('a', 'b');
            alter type status add value if not exists 'c';
            alter type status rename value 'a' to 'z';
            insert into storage.buckets (id, name, public) values ('media', 'media', false)
              on conflict (id) do nothing;
            """
        )
        assert _alive(replay) == {
            ("type", "status"),
            ("enum_value", "status:z"),
            ("enum_value", "status:b"),
            ("enum_value", "status:c"),
            ("bucket", "media"),
        }
        _replay("drop type status; create type status as enum ('x');", "m2.sql", replay)
        assert _alive(replay) == {
            ("type", "status"),
            ("enum_value", "status:x"),
            ("bucket", "media"),
        }

    def test_drop_column_and_index(self) -> None:
        replay = _replay(
            """
            create table foo (id int);
            alter table foo add column a int;
            create index foo_a on foo (a);
            alter table foo drop column if exists a;
            drop index if exists foo_a;
            """
        )
        assert _alive(replay) == {("table", "foo")}


class TestRealMigrations:
    def test_every_file_parses_and_key_objects_are_expected(self) -> None:
        migrations, objects = expected_objects()
        names = {(o.kind, o.name): o.migration for o in objects}
        assert len(migrations) >= 36
        assert names[("table", "inbound_jobs")] == "20260930000000_add_inbound_jobs.sql"
        assert ("table", "conversation_handoffs") in names
        assert names[("bucket", "conversation-media")].endswith(
            "_add_conversation_media_bucket.sql"
        )
        assert ("enum_value", "channel_type:whatsapp") in names
        assert ("index", "uq_conversations_external") in names
        # `user_role` se borró y se recreó: cuenta la migración que lo recreó.
        assert names[("type", "user_role")] == "20260522000001_remove_tenant_agent_role.sql"
        assert ("enum_value", "user_role:tenant_agent") not in names
        assert all(o.migration in migrations for o in objects)


def _live_from(objects: list[Any], *, drop: set[str] = frozenset(), buckets: bool = True):
    def names(kind: str) -> frozenset[str]:
        return frozenset(o.name for o in objects if o.kind == kind and o.name not in drop)

    return LiveSchema(
        tables=names("table"),
        columns=names("column"),
        indexes=names("index"),
        types=names("type"),
        enum_values=names("enum_value"),
        buckets=names("bucket") if buckets else None,
    )


class TestSchemaCheck:
    def test_all_applied(self) -> None:
        migrations, objects = expected_objects()
        check = schema_check(migrations, objects, _live_from(objects))
        assert check.status == "ok"
        assert "todas aplicadas" in check.detail

    def test_missing_migration_is_named_with_the_file(self) -> None:
        migrations, objects = expected_objects()
        missing = {
            o.name for o in objects if o.migration == "20261001000002_add_conversation_handoffs.sql"
        }
        check = schema_check(migrations, objects, _live_from(objects, drop=missing))
        assert check.status == "fail"
        assert "20261001000002_add_conversation_handoffs.sql: falta" in check.detail
        assert "supabase/migrations/20261001000002_add_conversation_handoffs.sql" in check.hint

    def test_partial_and_unverifiable_states(self) -> None:
        migrations, objects = expected_objects()
        target = "20261001000001_add_zernio_channel.sql"
        one = next(o.name for o in objects if o.migration == target)
        statuses = {
            s.migration: s.state
            for s in migration_statuses(migrations, objects, _live_from(objects, drop={one}))
        }
        assert statuses[target] == "partial"
        assert statuses["20260513000001_grants.sql"] == "unverifiable"

    def test_unreadable_buckets_are_not_reported_missing(self) -> None:
        migrations, objects = expected_objects()
        check = schema_check(migrations, objects, _live_from(objects, buckets=False))
        assert check.status == "ok"
        assert "storage.buckets" in check.detail

    async def test_platform_checks_without_migrations_dir(self, tmp_path: Path) -> None:
        checks = await platform_checks(conn=None, migrations_dir=tmp_path / "nope")  # type: ignore[arg-type]
        assert checks[0].status == "skip"


# ─── Checks de configuración ──────────────────────────────────────────────────


class TestHelpdeskChecks:
    def test_zendesk_primary_with_whatsapp_is_ok(self) -> None:
        checks = _by_id(helpdesk_checks(_snapshot(_zendesk(), _zernio())))
        assert checks["helpdesk.primary"].status == "ok"
        assert checks["helpdesk.handoff_target"].status == "ok"
        assert checks["helpdesk.zendesk.signature"].status == "ok"
        assert "helpdesk.zendesk.api_user" not in checks

    def test_no_primary_fails_only_with_whatsapp(self) -> None:
        secondary = _integration("helpdesk", "gorgias", primary=False)
        assert _by_id(helpdesk_checks(_snapshot(secondary)))["helpdesk.primary"].status == "warn"
        checks = _by_id(helpdesk_checks(_snapshot(secondary, _zernio())))
        assert checks["helpdesk.primary"].status == "fail"
        assert checks["helpdesk.handoff_target"].status == "fail"

    def test_chatwoot_primary_cannot_take_whatsapp_handoff(self) -> None:
        # s81: Marea tenía Chatwoot de primario y el handoff fallaba en vivo.
        cw = _integration("helpdesk", "chatwoot", credentials={"api_access_token": "t"})
        checks = _by_id(helpdesk_checks(_snapshot(cw, _zernio())))
        assert checks["helpdesk.handoff_target"].status == "fail"
        assert "chatwoot" in checks["helpdesk.handoff_target"].detail

    def test_unsigned_webhook_and_missing_api_user(self) -> None:
        zd = _integration(
            "helpdesk", "zendesk", config={"subdomain": SUBDOMAIN}, credentials={"client_id": "c"}
        )
        checks = _by_id(helpdesk_checks(_snapshot(zd, _zernio())))
        assert checks["helpdesk.zendesk.signature"].status == "warn"
        assert checks["helpdesk.zendesk.api_user"].status == "warn"
        assert "setup_zendesk_handoff_triggers" in checks["helpdesk.zendesk.api_user"].hint

    def test_undecryptable_credentials_fail(self) -> None:
        zd = _integration("helpdesk", "zendesk", credentials_error="no se pudieron descifrar")
        checks = _by_id(helpdesk_checks(_snapshot(zd)))
        assert checks["helpdesk.zendesk.credentials"].status == "fail"


class TestWhatsappConfigChecks:
    def test_without_whatsapp_is_skipped(self) -> None:
        checks = whatsapp_config_checks(_snapshot(_zendesk()))
        assert [c.status for c in checks] == ["skip"]

    def test_real_number_ok(self) -> None:
        checks = _by_id(whatsapp_config_checks(_snapshot(_zendesk(), _zernio())))
        assert checks["whatsapp.integration"].status == "ok"
        assert checks["whatsapp.credentials"].status == "ok"
        assert checks["whatsapp.reengagement_template"].status == "ok"

    def test_sandbox_warns_and_points_to_offboard(self) -> None:
        checks = _by_id(whatsapp_config_checks(_snapshot(_zendesk(), _zernio(sandbox=True))))
        assert checks["whatsapp.integration"].status == "warn"
        assert "offboard" in checks["whatsapp.integration"].hint
        assert "whatsapp.reengagement_template" not in checks

    def test_prepared_but_inactive_points_to_finalize(self) -> None:
        checks = _by_id(whatsapp_config_checks(_snapshot(_zendesk(), _zernio(active=False))))
        assert checks["whatsapp.integration"].status == "fail"
        assert "finalize" in checks["whatsapp.integration"].hint

    def test_missing_template_account_and_secret(self) -> None:
        zn = _zernio(account_id=None, reengagement_template=None)
        zn.credentials = {"api_key": "k"}
        checks = _by_id(whatsapp_config_checks(_snapshot(_zendesk(), zn)))
        assert checks["whatsapp.account"].status == "fail"
        assert checks["whatsapp.reengagement_template"].status == "fail"
        assert checks["whatsapp.credentials"].status == "fail"
        assert "webhook_secret" in checks["whatsapp.credentials"].detail


class TestOperationsChecks:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    def test_healthy(self) -> None:
        activity = ActivitySnapshot(
            last_inbound_by_channel={"whatsapp": self.now - timedelta(hours=3)}
        )
        checks = _by_id(operations_checks(_snapshot(activity=activity), now=self.now))
        assert checks["operations.last_inbound"].status == "ok"
        assert "whatsapp hace 3 h" in checks["operations.last_inbound"].detail
        assert checks["operations.stuck_jobs"].status == "ok"

    def test_no_traffic_failed_and_stuck(self) -> None:
        failed = ActivitySnapshot(failed_jobs_24h=2, last_job_error="boom " * 100)
        checks = _by_id(operations_checks(_snapshot(activity=failed), now=self.now))
        assert checks["operations.last_inbound"].status == "warn"
        assert checks["operations.stuck_jobs"].status == "warn"
        assert len(checks["operations.stuck_jobs"].detail) < 300

        stuck = ActivitySnapshot(stuck_jobs=1, failed_jobs_24h=5)
        checks = _by_id(operations_checks(_snapshot(activity=stuck), now=self.now))
        assert checks["operations.stuck_jobs"].status == "fail"
        assert "5 turno(s) fallido(s)" in checks["operations.stuck_jobs"].detail


# ─── Checks en vivo ───────────────────────────────────────────────────────────


def _zendesk_trigger(definition: dict[str, Any], trigger_id: int) -> dict[str, Any]:
    """Cómo devuelve Zendesk un trigger: la definición + id/active."""
    return {**json.loads(json.dumps(definition)), "id": trigger_id, "active": True}


def _inbound_trigger(*, excludes_handoff: bool = True) -> dict[str, Any]:
    conditions = [{"field": "update_type", "operator": "is", "value": "Create"}]
    if excludes_handoff:
        conditions.append(NOT_HANDOFF_CONDITION)
    body = json.dumps({"ticket_id": "{{ticket.id}}", "subdomain": SUBDOMAIN})
    return {
        "id": 1,
        "title": "Auyan · inbound",
        "active": True,
        "conditions": {"all": conditions, "any": []},
        "actions": [{"field": "notification_webhook", "value": [WEBHOOK_ID, body]}],
    }


class FakeZendesk:
    def __init__(
        self,
        *,
        webhooks: list[dict[str, Any]] | None = None,
        triggers: list[dict[str, Any]] | None = None,
    ) -> None:
        self.webhooks = (
            webhooks
            if webhooks is not None
            else [
                {
                    "id": WEBHOOK_ID,
                    "name": "Auyan",
                    "status": "active",
                    "endpoint": f"{API_BASE}/webhooks/zendesk",
                }
            ]
        )
        self.triggers = (
            triggers
            if triggers is not None
            else [
                _inbound_trigger(),
                _zendesk_trigger(reply_trigger(WEBHOOK_ID, SUBDOMAIN), 2),
                _zendesk_trigger(solved_trigger(WEBHOOK_ID, SUBDOMAIN), 3),
            ]
        )
        self.calls: list[tuple[str, str]] = []

    async def get_me(self) -> dict[str, Any]:
        return {"id": 42, "name": "Auyan AI", "role": "admin"}

    async def _request(self, method: str, path: str, **_: Any) -> dict[str, Any]:
        self.calls.append((method, path))
        assert method == "GET", "el doctor solo lee"
        if path == "/webhooks":
            return {"webhooks": self.webhooks}
        if path == "/triggers.json":
            return {"triggers": self.triggers, "next_page": None}
        raise AssertionError(path)


def _factory(fake: FakeZendesk):
    async def factory(creds: dict[str, Any], subdomain: str) -> FakeZendesk:
        assert subdomain == SUBDOMAIN
        return fake

    return factory


async def _zendesk_live(fake: FakeZendesk, *integrations: IntegrationSnapshot) -> dict[str, Any]:
    zd = _zendesk()
    checks = await zendesk_live_checks(
        _snapshot(zd, *integrations), zd, api_base_url=API_BASE, client_factory=_factory(fake)
    )
    return _by_id(checks)


class TestTriggerDrift:
    def test_identical_definition_has_no_drift(self) -> None:
        expected = reply_trigger(WEBHOOK_ID, SUBDOMAIN)
        assert trigger_drift(_zendesk_trigger(expected, 2), expected) == []

    def test_boolean_values_from_the_api_still_match(self) -> None:
        expected = reply_trigger(WEBHOOK_ID, SUBDOMAIN)
        existing = _zendesk_trigger(expected, 2)
        for condition in existing["conditions"]["all"]:
            if condition["field"] == "comment_is_public":
                condition["value"] = True
        assert trigger_drift(existing, expected) == []

    def test_detects_inactive_condition_and_body_changes(self) -> None:
        expected = solved_trigger(WEBHOOK_ID, SUBDOMAIN)
        existing = _zendesk_trigger(expected, 3)
        existing["active"] = False
        existing["conditions"]["all"][0]["operator"] = "changed_to"  # el bug de s81
        existing["actions"][0]["value"][1] = json.dumps({"ticket_id": "{{ticket.id}}"})
        problems = trigger_drift(existing, expected)
        assert len(problems) == 3


class TestZendeskLive:
    async def test_healthy_account(self) -> None:
        fake = FakeZendesk()
        checks = await _zendesk_live(fake, _zernio())
        assert {c.status for c in checks.values()} == {"ok"}
        assert checks["helpdesk.zendesk.handoff_reply_trigger"].detail.startswith("Coincide")
        assert all(method == "GET" for method, _ in fake.calls)

    async def test_without_whatsapp_handoff_triggers_are_not_checked(self) -> None:
        checks = await _zendesk_live(FakeZendesk(triggers=[_inbound_trigger()]))
        assert "helpdesk.zendesk.handoff_reply_trigger" not in checks
        assert checks["helpdesk.zendesk.inbound_trigger"].status == "ok"

    async def test_webhook_pointing_elsewhere_fails_and_stops(self) -> None:
        fake = FakeZendesk(
            webhooks=[{"id": "w", "endpoint": "https://old.up.railway.app/webhooks/zendesk"}]
        )
        checks = await _zendesk_live(fake, _zernio())
        assert checks["helpdesk.zendesk.webhook"].status == "fail"
        assert "railway" in checks["helpdesk.zendesk.webhook"].detail
        assert ("GET", "/triggers.json") not in fake.calls

    async def test_inactive_webhook_fails(self) -> None:
        fake = FakeZendesk()
        fake.webhooks[0]["status"] = "inactive"
        checks = await _zendesk_live(fake)
        assert checks["helpdesk.zendesk.webhook"].status == "fail"

    async def test_missing_handoff_triggers_and_leaky_inbound(self) -> None:
        fake = FakeZendesk(triggers=[_inbound_trigger(excludes_handoff=False)])
        checks = await _zendesk_live(fake, _zernio())
        assert checks["helpdesk.zendesk.inbound_trigger"].status == "warn"
        assert checks["helpdesk.zendesk.handoff_reply_trigger"].status == "fail"
        assert "no existe" in checks["helpdesk.zendesk.handoff_solved_trigger"].detail
        assert "--tenant marea-studio" in checks["helpdesk.zendesk.handoff_reply_trigger"].hint

    async def test_no_inbound_trigger_fails(self) -> None:
        checks = await _zendesk_live(FakeZendesk(triggers=[]))
        assert checks["helpdesk.zendesk.inbound_trigger"].status == "fail"

    async def test_api_user_mismatch_warns(self) -> None:
        zd = _zendesk(api_user_id="7")
        checks = _by_id(
            await zendesk_live_checks(
                _snapshot(zd), zd, api_base_url=API_BASE, client_factory=_factory(FakeZendesk())
            )
        )
        assert checks["helpdesk.zendesk.api_user"].status == "warn"


class TestZernioLive:
    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ({"status": "healthy", "platformConnection": {"status": "connected"}}, "ok"),
            (
                {
                    "status": "error",
                    "needsReconnect": True,
                    "issues": ["Token expired"],
                    "platformConnection": {"status": "disconnected"},
                },
                "fail",
            ),
            ({"status": "healthy", "platformConnection": {"status": "unknown"}}, "warn"),
            ({"status": "warning"}, "warn"),
            ({"data": {"status": "healthy"}}, "ok"),
        ],
    )
    def test_interpret_account_health(self, body: dict[str, Any], expected: str) -> None:
        assert interpret_account_health(body)[0] == expected

    async def test_calls_health_with_runtime_key(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "status": "error",
                    "issues": ["Number disconnected"],
                    "platformConnection": {"status": "disconnected", "phoneStatus": "BANNED"},
                },
            )

        zn = _zernio()
        checks = await zernio_live_checks(
            _snapshot(_zendesk(), zn), zn, transport=httpx.MockTransport(handler)
        )
        assert seen[0].url.path == "/api/v1/accounts/acc_1/health"
        assert seen[0].headers["Authorization"] == "Bearer zk_runtime"
        assert checks[0].status == "fail"
        assert "BANNED" in checks[0].detail
        assert "prepare" in (checks[0].hint or "")


class TestRunLiveChecks:
    async def test_http_errors_become_failed_checks(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"code": "invalid_api_key"})

        zn = _zernio()
        checks = _by_id(
            await run_live_checks(
                _snapshot(zn), api_base_url=API_BASE, zernio_transport=httpx.MockTransport(handler)
            )
        )
        assert checks["whatsapp.account_health"].status == "fail"
        assert "HTTP 401" in checks["whatsapp.account_health"].detail

    async def test_factory_exception_is_reported(self) -> None:
        async def broken(creds: dict[str, Any], subdomain: str) -> Any:
            request = httpx.Request("POST", "https://marea.zendesk.com/oauth/tokens")
            raise httpx.HTTPStatusError(
                "bad", request=request, response=httpx.Response(401, request=request)
            )

        checks = _by_id(
            await run_live_checks(
                _snapshot(_zendesk()), api_base_url=API_BASE, zendesk_client_factory=broken
            )
        )
        assert checks["helpdesk.zendesk.auth"].status == "fail"
        assert "HTTP 401 en /oauth/tokens" in checks["helpdesk.zendesk.auth"].detail

    async def test_unsupported_and_unready_integrations(self) -> None:
        gorgias_hd = _integration("helpdesk", "gorgias", credentials={"access_token": "t"})
        inactive = _zernio(active=False)
        checks = _by_id(await run_live_checks(_snapshot(gorgias_hd, inactive), api_base_url=None))
        assert checks["helpdesk.gorgias.live"].status == "skip"
        assert "whatsapp.account_health" not in checks


class TestBuildReport:
    async def test_report_orders_groups_and_takes_worst_status(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "healthy"})

        platform = [
            schema_check(*expected_objects(), _live_from(expected_objects()[1]))  # ok
        ]
        report = await build_report(
            _snapshot(_zendesk(), _zernio(sandbox=True)),
            platform,
            api_base_url=API_BASE,
            started=time.monotonic(),
            zendesk_client_factory=_factory(FakeZendesk()),
            zernio_transport=httpx.MockTransport(handler),
        )
        assert report.status == "warn"  # sandbox
        assert report.tenant_slug == "marea-studio"
        groups = [c.group for c in report.checks]
        assert groups == sorted(
            groups,
            key=["platform", "helpdesk", "whatsapp", "commerce", "operations"].index,
        )
        assert report.counts["fail"] == 0

        text = render(report)
        assert "Doctor · marea-studio" in text
        assert "── WhatsApp" in text
        assert "→ python -m scripts.onboard_whatsapp offboard" in text


def test_report_ids_are_stable_for_the_dashboard() -> None:
    """La web agrupa por `group` y usa `id` como key: no deben repetirse."""
    checks = helpdesk_checks(_snapshot(_zendesk(), _zernio())) + whatsapp_config_checks(
        _snapshot(_zendesk(), _zernio())
    )
    ids = [c.id for c in checks]
    assert len(ids) == len(set(ids))
    assert UUID(str(TENANT_ID))
