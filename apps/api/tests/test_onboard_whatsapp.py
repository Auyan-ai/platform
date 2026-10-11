"""Plan del onboarding de WhatsApp (scripts/onboard_whatsapp.py), sin red ni DB."""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.scripts.onboard_whatsapp import (
    WEBHOOK_EVENTS,
    ZernioIntegrationState,
    _parse_args,
    account_id_of,
    account_phone_of,
    api_key_request,
    connect_url_params,
    ensure_not_sandbox,
    handoff_target_warning,
    pick_whatsapp_account,
    reengagement_template_request,
    sandbox_account_id,
    webhook_request,
    webhook_url,
)


def test_api_key_is_limited_to_the_tenant_profile() -> None:
    body = api_key_request("marea-studio", "prof-1")
    assert body["scope"] == "profiles"
    assert body["profileIds"] == ["prof-1"]


def test_webhook_request_filters_by_profile_and_subscribes_events() -> None:
    body = webhook_request("marea", webhook_url("https://api.example/"), "s", profile_id="p1")
    assert body["url"] == "https://api.example/webhooks/zernio"
    assert body["profileIds"] == ["p1"]
    assert "accountIds" not in body
    assert body["events"] == WEBHOOK_EVENTS
    assert {"message.received", "message.sent", "message.failed"} <= set(body["events"])


def test_sandbox_webhook_has_no_account_filter() -> None:
    # El número del sandbox no es del equipo: filtrar por su cuenta da 404 en Zernio.
    body = webhook_request("marea", "https://x/webhooks/zernio", "s")
    assert "accountIds" not in body
    assert "profileIds" not in body


def test_sandbox_account_id_from_phone_numbers() -> None:
    payload = {"numbers": [], "sandbox": {"phoneNumber": "+1202", "accountId": "acc-sb"}}
    assert sandbox_account_id(payload) == "acc-sb"
    assert sandbox_account_id({"numbers": []}) is None


def test_connect_url_is_hosted_signup_in_spanish() -> None:
    params = connect_url_params("p1", "Marea Studio", None)
    assert params == {
        "profileId": "p1",
        "signup": "hosted",
        "brandName": "Marea Studio",
        "language": "es",
    }


def test_reengagement_template_is_utility_es_with_one_variable() -> None:
    body = reengagement_template_request("acc-1")
    assert (body["category"], body["language"], body["accountId"]) == ("UTILITY", "es", "acc-1")
    assert "{{1}}" in body["components"][0]["text"]


def test_pick_whatsapp_account_and_fields() -> None:
    accounts = [
        {"_id": "ig-1", "platform": "instagram"},
        {
            "_id": "wa-1",
            "platform": "whatsapp",
            "metadata": {"displayPhoneNumber": "+34 600 11 12 22"},
        },
    ]
    account = pick_whatsapp_account(accounts)
    assert account is not None
    assert account_id_of(account) == "wa-1"
    assert account_phone_of(account) == "+34600111222"
    assert pick_whatsapp_account([{"platform": "instagram"}]) is None


def test_state_redacts_secrets() -> None:
    state = ZernioIntegrationState(
        credentials={"api_key": "sk_live_abcdef1234", "webhook_secret": "deadbeef"},
        config={"profile_id": "p1"},
    )
    redacted = state.redacted()
    assert redacted["credentials"]["api_key"] == "***1234"
    assert redacted["credentials"]["webhook_secret"] == "***"


def test_cli_requires_staging_flag_to_exist_for_sandbox() -> None:
    args = _parse_args(["sandbox", "--tenant", "marea", "--phone", "+34600111222", "--staging"])
    assert args.staging is True and args.account_id is None
    args = _parse_args(["prepare", "--tenant", "marea", "--brand", "Marea", "--dry-run"])
    assert (args.command, args.dry_run, args.rotate_key) == ("prepare", True, False)


def test_onboarding_warns_when_escalations_cannot_reach_a_person() -> None:
    """s81: Marea tenía Chatwoot como helpdesk primario y el handoff fallaba en vivo."""
    assert "no tiene helpdesk primario" in (handoff_target_warning(None) or "")
    assert "no admite handoff" in (handoff_target_warning("chatwoot") or "")
    assert handoff_target_warning("zendesk") is None


def test_prepare_refuses_a_tenant_with_the_sandbox_registered() -> None:
    """s81: `prepare` habría reutilizado la key de alcance completo y el webhook sin filtro
    del sandbox para el número real."""
    with pytest.raises(SystemExit, match="offboard"):
        ensure_not_sandbox(ZernioIntegrationState(config={"account_id": "a", "sandbox": True}))
    ensure_not_sandbox(ZernioIntegrationState(config={"profile_id": "p1"}))


# ─── Idempotencia, dry-run y secretos (Zernio y Supabase simulados) ───────────

import copy  # noqa: E402
import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from uuid import uuid4  # noqa: E402

import httpx  # noqa: E402
from apps.api.scripts import onboard_whatsapp as ow  # noqa: E402

MASTER_KEY = "zrk_MASTER_SECRET_SHOULD_NEVER_APPEAR"
CREATED_KEY = "zrk_created_runtime_key_value"
SLUG = "marea-studio"
RUNTIME_KEY_NAME = f"auyan-{SLUG}-runtime"


class FakeZernio:
    """Zernio en memoria. `GET /api-keys` filtra la key maestra como el real."""

    def __init__(self) -> None:
        self.profiles: list[dict] = []
        self.keys: list[dict] = []
        self.webhooks: list[dict] = []
        self.accounts: list[dict] = []
        self.templates: list[dict] = []
        self.calls: list[tuple[str, str]] = []
        self.fail_once: set[tuple[str, str]] = set()
        self.last_connect_params: dict[str, str] = {}
        self.extra_routes: dict[tuple[str, str], dict] = {}
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path.removeprefix("/v1")
        self.calls.append((method, path))
        if (method, path) in self.fail_once:
            self.fail_once.discard((method, path))
            return httpx.Response(500, json={"error": "boom"})
        if (method, path) in self.extra_routes:
            return httpx.Response(200, json=self.extra_routes[(method, path)])
        body = json.loads(request.content) if request.content else {}
        if (method, path) == ("GET", "/profiles"):
            return httpx.Response(200, json={"profiles": self.profiles})
        if (method, path) == ("POST", "/profiles"):
            profile = {"_id": self._id("prof"), "name": body["name"]}
            self.profiles.append(profile)
            return httpx.Response(200, json={"profile": profile})
        if (method, path) == ("GET", "/api-keys"):
            return httpx.Response(
                200, json={"apiKeys": copy.deepcopy(self.keys), "firstApiKey": MASTER_KEY}
            )
        if (method, path) == ("POST", "/api-keys"):
            key = {"id": self._id("key"), "name": body["name"], "scope": body["scope"]}
            self.keys.append(key)
            return httpx.Response(200, json={"apiKey": {**key, "key": CREATED_KEY}})
        if method == "DELETE" and path.startswith("/api-keys/"):
            key_id = path.rsplit("/", 1)[1]
            before = len(self.keys)
            self.keys = [k for k in self.keys if k["id"] != key_id]
            return httpx.Response(200 if len(self.keys) < before else 404, json={})
        if (method, path) == ("GET", "/webhooks/settings"):
            return httpx.Response(200, json={"webhooks": copy.deepcopy(self.webhooks)})
        if (method, path) == ("POST", "/webhooks/settings"):
            hook = {"_id": self._id("hook"), "name": body["name"], "url": body["url"]}
            self.webhooks.append(hook)
            return httpx.Response(200, json={"webhook": hook})
        if (method, path) == ("DELETE", "/webhooks/settings"):
            hook_id = request.url.params["webhookId"]
            before = len(self.webhooks)
            self.webhooks = [w for w in self.webhooks if w["_id"] != hook_id]
            return httpx.Response(200 if len(self.webhooks) < before else 404, json={})
        if (method, path) == ("GET", "/connect/whatsapp"):
            self.last_connect_params = dict(request.url.params)
            return httpx.Response(200, json={"authUrl": "https://signup.example/x"})
        if (method, path) == ("GET", "/accounts"):
            return httpx.Response(200, json={"accounts": self.accounts})
        if (method, path) == ("GET", "/whatsapp/templates"):
            return httpx.Response(200, json={"templates": self.templates})
        if (method, path) == ("POST", "/whatsapp/templates"):
            self.templates.append({"name": body["name"], "language": body["language"]})
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": f"unhandled {method} {path}"})

    def admin(self) -> ow.ZernioAdmin:
        return ow.ZernioAdmin(
            "zrk_master", "https://zernio.test/v1", transport=httpx.MockTransport(self.handler)
        )

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] != "GET"]

    def creates(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] == "POST"]


class FakeDb:
    """Sustituye la integración guardada (credenciales + config) en Supabase."""

    def __init__(self) -> None:
        self.row: ow.ZernioIntegrationState | None = None
        self.deleted = False
        self.saves = 0
        self.fail_next_save = False

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tenant_id = uuid4()
        current = SimpleNamespace(id=uuid4())

        async def resolve(conn: Any, tenant: str) -> Any:
            return tenant_id

        async def load(conn: Any, tid: Any, key: bytes) -> Any:
            if self.row is None:
                return None, ow.ZernioIntegrationState()
            return current, copy.deepcopy(self.row)

        async def save(conn: Any, tid: Any, key: bytes, state: Any) -> None:
            if self.fail_next_save:
                self.fail_next_save = False
                raise RuntimeError("supabase caído")
            self.saves += 1
            self.row = copy.deepcopy(state)

        async def soft_delete(conn: Any, *, tenant_id: Any, integration_id: Any) -> bool:
            self.deleted = True
            self.row = None
            return True

        async def no_warn(conn: Any, tid: Any) -> None:
            return None

        monkeypatch.setattr(ow, "_resolve_tenant_id", resolve)
        monkeypatch.setattr(ow, "_load_state", load)
        monkeypatch.setattr(ow, "_save_state", save)
        monkeypatch.setattr(ow, "soft_delete_integration", soft_delete)
        monkeypatch.setattr(ow, "_warn_handoff_target", no_warn)
        monkeypatch.setenv("AUYAN_API_BASE_URL", "https://api.example")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeZernio, FakeDb]:
    zernio, db = FakeZernio(), FakeDb()
    db.install(monkeypatch)
    return zernio, db


async def run(argv: list[str], zernio: FakeZernio) -> None:
    args = ow._parse_args(argv)
    admin = zernio.admin()
    try:
        await ow.COMMANDS[args.command](args, None, admin, b"k")
    finally:
        await admin.close()


PREPARE = ["prepare", "--tenant", SLUG, "--brand", "Marea Studio"]
WA_ACCOUNT = {"_id": "wa-1", "platform": "whatsapp", "phoneNumber": "+34600111222"}


async def test_prepare_twice_second_run_creates_nothing(
    world: tuple[FakeZernio, FakeDb], capsys: pytest.CaptureFixture[str]
) -> None:
    zernio, db = world
    await run(PREPARE, zernio)
    assert sorted(zernio.creates()) == [
        ("POST", "/api-keys"),
        ("POST", "/profiles"),
        ("POST", "/webhooks/settings"),
    ]
    zernio.calls.clear()
    capsys.readouterr()

    await run(PREPARE, zernio)

    assert zernio.writes() == []
    out = capsys.readouterr().out
    assert "profile: reused" in out and "api_key: reused" in out and "webhook: reused" in out
    assert (len(zernio.profiles), len(zernio.keys), len(zernio.webhooks)) == (1, 1, 1)
    assert db.row is not None and db.row.credentials["api_key"] == CREATED_KEY


async def test_prepare_failing_midway_then_rerun_reuses_without_duplicates(
    world: tuple[FakeZernio, FakeDb],
) -> None:
    zernio, db = world
    zernio.fail_once.add(("POST", "/webhooks/settings"))
    with pytest.raises(SystemExit):
        await run(PREPARE, zernio)
    assert db.row is not None and db.row.credentials["api_key"] == CREATED_KEY
    assert (len(zernio.profiles), len(zernio.keys), len(zernio.webhooks)) == (1, 1, 0)

    await run(PREPARE, zernio)

    assert (len(zernio.profiles), len(zernio.keys), len(zernio.webhooks)) == (1, 1, 1)
    assert db.row.config["webhook_id"] == zernio.webhooks[0]["_id"]
    assert db.row.credentials["webhook_secret"]


async def test_failed_save_after_creating_the_key_rolls_it_back(
    world: tuple[FakeZernio, FakeDb], capsys: pytest.CaptureFixture[str]
) -> None:
    zernio, db = world
    zernio.profiles.append({"_id": "prof-x", "name": f"auyan-{SLUG}"})
    db.row = ow.ZernioIntegrationState(config={"profile_id": "prof-x"})
    db.fail_next_save = True

    with pytest.raises(RuntimeError, match="supabase caído"):
        await run(PREPARE, zernio)

    assert zernio.keys == []
    assert "rollback de la key" in capsys.readouterr().out


async def test_orphan_key_with_our_name_is_deleted_and_replaced(
    world: tuple[FakeZernio, FakeDb], capsys: pytest.CaptureFixture[str]
) -> None:
    """s81: una key creada en Zernio y no guardada. Su valor no se recupera: se borra."""
    zernio, _ = world
    zernio.keys.append({"id": "key-orphan", "name": RUNTIME_KEY_NAME, "scope": "profiles"})
    zernio.keys.append({"id": "key-other", "name": "otra-cosa", "scope": "full"})

    await run(PREPARE, zernio)

    ours = [k["id"] for k in zernio.keys if k["name"] == RUNTIME_KEY_NAME]
    assert len(ours) == 1 and ours != ["key-orphan"]
    assert any(k["id"] == "key-other" for k in zernio.keys)
    assert "huérfana" in capsys.readouterr().out


async def test_dry_run_performs_no_writes_and_reports_the_plan(
    world: tuple[FakeZernio, FakeDb], capsys: pytest.CaptureFixture[str]
) -> None:
    zernio, db = world
    zernio.keys.append({"id": "key-orphan", "name": RUNTIME_KEY_NAME, "scope": "profiles"})

    await run([*PREPARE, "--dry-run"], zernio)

    assert zernio.writes() == []
    assert db.saves == 0 and db.row is None
    out = capsys.readouterr().out
    assert "[dry-run] profile: created" in out
    assert "[dry-run] api_key: deleted" in out and "key-orphan" in out
    assert "[dry-run] api_key: created" in out
    assert "[dry-run] webhook: created" in out
    assert "Resumen (dry-run: no se escribió nada)" in out


async def test_admin_blocks_writes_in_dry_run() -> None:
    zernio = FakeZernio()
    admin = zernio.admin()
    admin.dry_run = True
    with pytest.raises(RuntimeError, match="dry-run"):
        await admin.request("POST", "/profiles", json={"name": "x"})
    with pytest.raises(RuntimeError, match="dry-run"):
        await admin.delete("/api-keys/k1")
    assert zernio.calls == []
    await admin.close()


async def test_output_never_contains_key_material(
    world: tuple[FakeZernio, FakeDb], capsys: pytest.CaptureFixture[str]
) -> None:
    zernio, db = world
    zernio.keys.append({"id": "key-orphan", "name": RUNTIME_KEY_NAME, "scope": "profiles"})
    await run([*PREPARE, "--dry-run"], zernio)
    await run(PREPARE, zernio)
    assert db.row is not None
    webhook_secret = db.row.credentials["webhook_secret"]
    await run(PREPARE, zernio)
    await run(["offboard", "--tenant", SLUG, "--dry-run"], zernio)
    await run(["offboard", "--tenant", SLUG], zernio)
    assert db.row is None

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "key-orphan" in text
    for forbidden in (MASTER_KEY, CREATED_KEY, "zrk_master", webhook_secret):
        assert forbidden not in text


async def test_api_key_error_body_is_never_echoed() -> None:
    def leak(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=f"forbidden {MASTER_KEY}")

    admin = ow.ZernioAdmin(
        "zrk_master", "https://zernio.test/v1", transport=httpx.MockTransport(leak)
    )
    with pytest.raises(SystemExit) as exc:
        await admin.request("GET", "/api-keys")
    assert MASTER_KEY not in str(exc.value) and "403" in str(exc.value)
    await admin.close()


def test_listing_with_unexpected_shape_fails_closed() -> None:
    with pytest.raises(SystemExit, match="forma inesperada") as exc:
        ow.parse_remote_keys({"firstApiKey": MASTER_KEY})
    assert MASTER_KEY not in str(exc.value)


def test_remote_keys_keep_only_whitelisted_fields() -> None:
    keys = ow.parse_remote_keys(
        {"apiKeys": [{"id": "k1", "name": "n", "scope": "full", "key": "zrk_x", "firstApiKey": 1}]}
    )
    assert keys == [ow.RemoteKey("k1", "n", "full", ())]
    assert "zrk_x" not in repr(keys)


async def test_onboarding_api_is_passed_to_connect(world: tuple[FakeZernio, FakeDb]) -> None:
    zernio, _ = world
    await run([*PREPARE, "--onboarding", "api"], zernio)
    assert zernio.last_connect_params["onboarding"] == "api"
    assert zernio.last_connect_params["signup"] == "hosted"


async def test_default_onboarding_keeps_coexistence_params(
    world: tuple[FakeZernio, FakeDb],
) -> None:
    zernio, _ = world
    await run(PREPARE, zernio)
    assert "onboarding" not in zernio.last_connect_params


def test_onboarding_rejects_unknown_mode() -> None:
    with pytest.raises(SystemExit):
        ow._parse_args([*PREPARE, "--onboarding", "nope"])
    assert connect_url_params("p", "B", None, "api")["onboarding"] == "api"


async def test_prepare_skips_signup_link_when_whatsapp_already_connected(
    world: tuple[FakeZernio, FakeDb], capsys: pytest.CaptureFixture[str]
) -> None:
    zernio, _ = world
    await run(PREPARE, zernio)
    zernio.accounts.append(WA_ACCOUNT)
    zernio.calls.clear()
    await run(PREPARE, zernio)
    assert ("GET", "/connect/whatsapp") not in zernio.calls
    assert "signup_link: skipped" in capsys.readouterr().out


async def test_finalize_twice_creates_template_once_and_is_noop_after(
    world: tuple[FakeZernio, FakeDb], capsys: pytest.CaptureFixture[str]
) -> None:
    zernio, db = world
    await run(PREPARE, zernio)
    zernio.accounts.append(WA_ACCOUNT)
    await run(["finalize", "--tenant", SLUG], zernio)
    assert db.row is not None and db.row.is_active and db.row.config["account_id"] == "wa-1"
    assert len(zernio.templates) == 1
    zernio.calls.clear()
    saves = db.saves
    capsys.readouterr()

    await run(["finalize", "--tenant", SLUG], zernio)

    assert zernio.writes() == [] and db.saves == saves
    out = capsys.readouterr().out
    assert "integration: reused" in out and "template: reused" in out


async def test_finalize_dry_run_writes_nothing(world: tuple[FakeZernio, FakeDb]) -> None:
    zernio, db = world
    await run(PREPARE, zernio)
    zernio.accounts.append(WA_ACCOUNT)
    zernio.calls.clear()
    saves = db.saves
    await run(["finalize", "--tenant", SLUG, "--dry-run"], zernio)
    assert zernio.writes() == [] and db.saves == saves
    assert db.row is not None and not db.row.is_active


async def test_rotate_key_replaces_the_old_key_after_saving_the_new_one(
    world: tuple[FakeZernio, FakeDb],
) -> None:
    zernio, db = world
    await run(PREPARE, zernio)
    old_id = zernio.keys[0]["id"]
    await run([*PREPARE, "--rotate-key"], zernio)
    assert len(zernio.keys) == 1 and zernio.keys[0]["id"] != old_id
    assert db.row is not None and db.row.config["api_key_id"] == zernio.keys[0]["id"]


async def test_offboard_is_rerunnable_and_removes_orphans(
    world: tuple[FakeZernio, FakeDb], capsys: pytest.CaptureFixture[str]
) -> None:
    zernio, db = world
    await run(PREPARE, zernio)
    zernio.keys.append({"id": "key-orphan", "name": f"auyan-{SLUG}-sandbox", "scope": "full"})
    await run(["offboard", "--tenant", SLUG, "--dry-run"], zernio)
    assert len(zernio.keys) == 2 and not db.deleted

    await run(["offboard", "--tenant", SLUG], zernio)
    assert zernio.keys == [] and zernio.webhooks == [] and db.deleted
    capsys.readouterr()

    await run(["offboard", "--tenant", SLUG], zernio)
    assert "integration: skipped" in capsys.readouterr().out


async def test_sandbox_twice_is_a_noop_and_refuses_a_real_profile(
    world: tuple[FakeZernio, FakeDb],
) -> None:
    zernio, db = world
    zernio.extra_routes[("GET", "/phone-numbers")] = {"sandbox": {"accountId": "acc-sb"}}
    zernio.extra_routes[("POST", "/whatsapp/sandbox/sessions")] = {}
    argv = ["sandbox", "--tenant", SLUG, "--phone", "+34600111222", "--staging"]
    await run(argv, zernio)
    assert ("POST", "/whatsapp/sandbox/sessions") in zernio.calls
    zernio.calls.clear()

    await run(argv, zernio)

    assert zernio.writes() == []
    assert len(zernio.keys) == 1 and len(zernio.webhooks) == 1

    db.row = ow.ZernioIntegrationState(config={"profile_id": "p1"})
    with pytest.raises(SystemExit, match="offboard"):
        await run(argv, zernio)
