"""Plan del onboarding de WhatsApp (scripts/onboard_whatsapp.py), sin red ni DB."""

from __future__ import annotations

from apps.api.scripts.onboard_whatsapp import (
    WEBHOOK_EVENTS,
    ZernioIntegrationState,
    _parse_args,
    account_id_of,
    account_phone_of,
    api_key_request,
    connect_url_params,
    pick_whatsapp_account,
    reengagement_template_request,
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


def test_sandbox_webhook_filters_by_account() -> None:
    body = webhook_request("marea", "https://x/webhooks/zernio", "s", account_id="acc-sb")
    assert body["accountIds"] == ["acc-sb"]
    assert "profileIds" not in body


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
        {"_id": "wa-1", "platform": "whatsapp", "metadata": {"displayPhoneNumber": "+34 600 11 12 22"}},
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
