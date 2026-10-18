"""Adjuntos de WhatsApp: Storage, transcripción, marca de imagen y mensajes fijos (PR-7)."""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from apps.api.core.errors import ExternalIntegrationError
from apps.api.db.inbound_jobs import ClaimedInboundJob
from apps.api.integrations.base import StoredAttachment
from apps.api.integrations.transcription import Transcript, get_transcriber, ogg_duration_seconds
from apps.api.integrations.transcription.openai_transcriber import OpenAITranscriber
from apps.api.services import media_storage
from apps.api.services.fixed_texts import fixed_text
from apps.api.services.inbound_media import (
    chat_escalation_ack,
    fallback_message,
    process_inbound_media,
    unseen_media_marker,
)

from tests.conftest import (
    CONVERSATION_ID,
    CUSTOMER_ID,
    INBOUND_MSG_ID,
    TENANT_ID,
    make_conversation,
    make_fake_tenant_scope,
    make_message,
)

MOD = "apps.api.services.inbound_media"


def ogg(seconds: float, pre_skip: int = 312) -> bytes:
    """OGG/Opus mínimo: página con OpusHead + última página con el granule position."""
    head = b"OpusHead" + bytes([1, 1]) + struct.pack("<H", pre_skip) + b"\x80\xbb\x00\x00"
    first = b"OggS" + b"\x00\x02" + struct.pack("<q", 0) + b"\x00" * 13 + head
    granule = int(seconds * 48000) + pre_skip
    last = b"OggS" + b"\x00\x04" + struct.pack("<q", granule) + b"\x00" * 13
    return first + b"audio-bytes" + last


class _Settings:
    transcription_provider: str | None = "openai"
    transcription_model = "gpt-4o-transcribe"
    transcription_max_seconds = 300
    transcription_cost_per_minute_usd = 0.006


def _job() -> ClaimedInboundJob:
    return ClaimedInboundJob(
        id=UUID(int=1),
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        inbound_message_id=INBOUND_MSG_ID,
        end_customer_id=CUSTOMER_ID,
        channel="whatsapp",
        attempts=1,
        max_attempts=3,
        absorbed_message_ids=(),
        is_retry=False,
        enqueued_at=datetime.now(UTC),
    )


def _msg(text: str, *items: dict[str, Any], **meta: Any) -> Any:
    return make_message(
        id=INBOUND_MSG_ID,
        content=text,
        metadata={"zernio_attachments": list(items), **meta},
    )


IMAGE = {"type": "image", "url": "https://zernio.com/api/v1/whatsapp/media/1", "mime_type": None}
AUDIO = {"type": "audio", "url": "https://zernio.com/api/v1/whatsapp/media/2", "mime_type": None}
STICKER = {"type": "sticker", "url": "https://zernio.com/api/v1/whatsapp/media/3"}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    client = MagicMock()
    client.download_media = AsyncMock(return_value=(b"\x89PNG", "image/png"))
    adapter = MagicMock()
    adapter.client = MagicMock(return_value=client)
    transcriber = MagicMock()
    transcriber.transcribe = AsyncMock(
        return_value=Transcript(
            text="quiero cambiar la dirección del pedido mil cuatrocientos treinta y dos",
            duration_s=7.0,
            provider="openai",
            model="gpt-4o-transcribe",
            cost_usd=0.0007,
        )
    )

    async def _store(**kwargs: Any) -> StoredAttachment:
        path = media_storage.attachment_path(
            kwargs["tenant_id"],
            kwargs["conversation_id"],
            kwargs["message_id"],
            kwargs["idx"],
            kwargs["mime_type"],
        )
        return StoredAttachment(
            path=path,
            mime_type=kwargs["mime_type"],
            size=len(kwargs["content"]),
            filename=path.rsplit("/", 1)[-1],
            kind=kwargs["kind"],
        )

    m: dict[str, Any] = {
        "get_inbound_messages": AsyncMock(return_value=[]),
        "update_inbound_message_media": AsyncMock(),
        "load_delivery_client": AsyncMock(return_value=(adapter, object())),
        "store_attachment": AsyncMock(side_effect=_store),
        "get_transcriber": MagicMock(return_value=transcriber),
    }
    for name, mock in m.items():
        monkeypatch.setattr(f"{MOD}.{name}", mock)
    monkeypatch.setattr(f"{MOD}.tenant_scope", make_fake_tenant_scope())
    m.update(client=client, transcriber=transcriber)
    return m


async def _process(env: dict[str, Any], *messages: Any, observability: Any = None) -> Any:
    env["get_inbound_messages"].return_value = list(messages)
    return await process_inbound_media(
        job=_job(),
        conversation=make_conversation(channel="whatsapp", external_id="zconv-1"),
        settings=_Settings(),  # type: ignore[arg-type]
        observability=observability,
    )


async def test_voice_note_is_transcribed(env: dict[str, Any]) -> None:
    env["client"].download_media.return_value = (ogg(7), "audio/ogg")
    observability = MagicMock()
    out = await _process(env, _msg("", AUDIO), observability=observability)
    assert out.texts == [
        "[Nota de voz] quiero cambiar la dirección del pedido mil cuatrocientos treinta y dos"
    ]
    assert out.fallback_kind is None
    assert out.transcription_cost_usd == pytest.approx(0.0007)
    update = env["update_inbound_message_media"].await_args.kwargs
    assert update["content"].startswith("[Nota de voz] ")
    assert update["metadata_patch"]["transcription"][0]["provider"] == "openai"
    assert update["attachments"][0]["path"].startswith(f"{TENANT_ID}/{CONVERSATION_ID}/")
    run = observability.record_standalone_run.call_args.kwargs
    assert run["name"] == "transcribe_audio"
    assert run["metadata"]["conversation_id"] == str(CONVERSATION_ID)
    assert "text" not in json.dumps(run["outputs"])


async def test_image_with_text_runs_graph_with_marker(env: dict[str, Any]) -> None:
    out = await _process(env, _msg("¿me llegó roto?", IMAGE))
    assert out.texts == [
        "¿me llegó roto?\n\n[adjuntó 1 imagen que no puedes ver; no describas su contenido]"
    ]
    assert out.fallback_kind is None
    assert out.attachments[0].kind == "image"


async def test_image_without_text_gets_fixed_message(env: dict[str, Any]) -> None:
    out = await _process(env, _msg("", IMAGE))
    assert out.texts == []
    assert out.fallback_kind == "media_without_text"
    assert len(out.attachments) == 1


async def test_download_failure_gets_fixed_message(env: dict[str, Any]) -> None:
    env["client"].download_media.side_effect = ExternalIntegrationError("x", code="zernio_x")
    out = await _process(env, _msg("", IMAGE))
    assert out.fallback_kind == "download_failed"
    assert out.attachments == []


async def test_long_voice_note_is_not_transcribed(env: dict[str, Any]) -> None:
    env["client"].download_media.return_value = (ogg(301), "audio/ogg")
    out = await _process(env, _msg("", AUDIO))
    assert out.fallback_kind == "audio_too_long"
    env["transcriber"].transcribe.assert_not_awaited()


async def test_no_provider_asks_to_write(env: dict[str, Any]) -> None:
    env["get_transcriber"].return_value = None
    env["client"].download_media.return_value = (ogg(5), "audio/ogg")
    out = await _process(env, _msg("", AUDIO))
    assert out.fallback_kind == "audio_unavailable"


async def test_transcription_error_asks_to_write(env: dict[str, Any]) -> None:
    env["client"].download_media.return_value = (ogg(5), "audio/ogg")
    env["transcriber"].transcribe.side_effect = RuntimeError("provider down")
    out = await _process(env, _msg("", AUDIO))
    assert out.fallback_kind == "audio_unavailable"


async def test_sticker_is_unsupported(env: dict[str, Any]) -> None:
    out = await _process(env, _msg("", STICKER))
    assert out.fallback_kind == "unsupported"
    env["client"].download_media.assert_not_awaited()


async def test_text_message_without_media_is_untouched(env: dict[str, Any]) -> None:
    out = await _process(env, make_message(id=INBOUND_MSG_ID, content="hola", metadata={}))
    assert out.texts == ["hola"]
    env["update_inbound_message_media"].assert_not_awaited()
    env["load_delivery_client"].assert_not_awaited()


async def test_already_processed_message_is_not_downloaded_again(env: dict[str, Any]) -> None:
    msg = make_message(
        id=INBOUND_MSG_ID,
        content="[Nota de voz] hola",
        attachments=[{"path": "t/c/m/0.ogg", "mime_type": "audio/ogg", "kind": "audio"}],
        metadata={"zernio_attachments": [AUDIO], "media_processed": True},
    )
    out = await _process(env, msg)
    assert out.texts == ["[Nota de voz] hola"]
    env["client"].download_media.assert_not_awaited()
    assert out.attachments[0].path == "t/c/m/0.ogg"


async def test_burst_with_one_text_runs_graph(env: dict[str, Any]) -> None:
    other = make_message(id=UUID(int=77), content="es el #1432", metadata={})
    out = await _process(env, _msg("", IMAGE), other)
    assert out.texts == ["es el #1432"]
    assert out.fallback_kind is None


# ─── Utilidades ───────────────────────────────────────────────────────────────


def test_marker_wording() -> None:
    assert unseen_media_marker(1, 0) == (
        "[adjuntó 1 imagen que no puedes ver; no describas su contenido]"
    )
    assert unseen_media_marker(2, 1) == (
        "[adjuntó 2 imágenes y 1 archivo que no puedes ver; no describas su contenido]"
    )


def test_fallback_messages_are_configurable() -> None:
    assert fallback_message("audio_unavailable", None) == fixed_text("audio_unavailable", "es")
    cfg = {"media_fallback_messages": {"audio_unavailable": "Escríbenos, porfa"}}
    assert fallback_message("audio_unavailable", cfg) == "Escríbenos, porfa"


def test_fallback_messages_speak_the_conversation_language() -> None:
    assert fallback_message("audio_unavailable", None, language="en") == (
        "We couldn't listen to your voice note. Could you write your question for us, please?"
    )
    assert fallback_message("media_without_text", None, language="ca").startswith("Gràcies!")
    assert fallback_message("download_failed", None, language="fr").startswith("Nous n'avons pas")
    # Un tipo desconocido cae al texto genérico, también traducido.
    assert fallback_message("whatever", None, language="en") == fixed_text("unsupported", "en")


def test_fallback_overrides_are_per_language() -> None:
    cfg = {
        "media_fallback_messages": {
            "audio_unavailable": {"en": "Please type it, thanks"},
            "unsupported": "Escríbenos, porfa",
        }
    }
    assert fallback_message("audio_unavailable", cfg, language="en") == "Please type it, thanks"
    assert fallback_message("audio_unavailable", cfg, language="fr").startswith("Nous n'avons pas")
    assert fallback_message("unsupported", cfg, language="es") == "Escríbenos, porfa"
    assert fallback_message("unsupported", cfg, language="en").startswith("How can we help")
    assert fallback_message("unsupported", cfg, language="en", tenant_default="en") == (
        "Escríbenos, porfa"
    )


def test_chat_escalation_ack_speaks_the_conversation_language() -> None:
    ack = chat_escalation_ack("escalate", None, "low_confidence", escalated=True, language="en")
    assert ack == "I've passed your question to our team. They'll reply here as soon as possible."


async def test_worker_fixed_message_uses_the_conversation_language(
    worker: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apps.api.services.inbound_worker.conversation_text_languages",
        AsyncMock(return_value=("en", "es")),
    )
    assert await _run(worker) == "media_fallback"
    assert worker["insert_message"].await_args.kwargs["content"] == fixed_text(
        "media_without_text", "en"
    )


def test_ogg_duration() -> None:
    assert ogg_duration_seconds(ogg(7)) == pytest.approx(7.0)
    assert ogg_duration_seconds(b"not ogg") is None


def test_attachment_path_is_tenant_scoped() -> None:
    path = media_storage.attachment_path(TENANT_ID, CONVERSATION_ID, INBOUND_MSG_ID, 0, "audio/ogg")
    assert path == f"{TENANT_ID}/{CONVERSATION_ID}/{INBOUND_MSG_ID}/0.ogg"
    assert media_storage.extension_for("image/jpeg") == "jpg"
    assert media_storage.extension_for("application/x-unknown") == "bin"


def test_get_transcriber() -> None:
    settings = MagicMock(transcription_provider=None)
    assert get_transcriber(settings) is None
    settings = MagicMock(transcription_provider="openai", transcription_model="m")
    settings.openai_api_key.get_secret_value.return_value = "sk"
    settings.transcription_cost_per_minute_usd = 0.006
    assert isinstance(get_transcriber(settings), OpenAITranscriber)
    settings.transcription_provider = "nope"
    with pytest.raises(ValueError):
        get_transcriber(settings)


async def test_openai_transcriber_request_and_cost() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = request.content
        return httpx.Response(200, json={"text": " hola, mi pedido es el 1432 "})

    t = OpenAITranscriber(
        api_key="sk", cost_per_minute_usd=0.006, transport=httpx.MockTransport(handler)
    )
    result = await t.transcribe(ogg(60), "audio/ogg")
    assert result.text == "hola, mi pedido es el 1432"
    assert result.cost_usd == pytest.approx(0.006)
    assert seen["auth"] == "Bearer sk"
    assert b'name="language"' in seen["body"] and b"gpt-4o-transcribe" in seen["body"]


# ─── Storage ──────────────────────────────────────────────────────────────────


async def test_store_and_download_use_private_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer srk"
        if request.method == "GET":
            return httpx.Response(200, content=b"data")
        return httpx.Response(200, json={"Key": "x"})

    settings = MagicMock()
    settings.supabase_url = "https://proj.supabase.co"
    settings.supabase_service_role_key.get_secret_value.return_value = "srk"
    monkeypatch.setattr(media_storage, "get_settings", lambda: settings)
    monkeypatch.setattr(media_storage, "_transport", httpx.MockTransport(handler))
    stored = await media_storage.store_attachment(
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        message_id=INBOUND_MSG_ID,
        idx=0,
        content=b"data",
        mime_type="image/jpeg",
        kind="image",
    )
    assert await media_storage.download_attachment(stored.path) == b"data"
    assert calls[0] == (
        "POST",
        f"/storage/v1/object/conversation-media/{TENANT_ID}/{CONVERSATION_ID}/{INBOUND_MSG_ID}/0.jpg",
    )
    assert calls[1][1].startswith("/storage/v1/object/authenticated/conversation-media/")


def _storage_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.supabase_url = "https://proj.supabase.co"
    settings.supabase_service_role_key.get_secret_value.return_value = "srk"
    monkeypatch.setattr(media_storage, "get_settings", lambda: settings)


async def test_signed_url_matches_supabase_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forma real de la respuesta de Supabase, verificada contra staging en s81:
    `{"signedURL": "/object/sign/<bucket>/<path>?token=…"}`, relativa a `/storage/v1`."""
    path = f"{TENANT_ID}/{CONVERSATION_ID}/{INBOUND_MSG_ID}/0.jpg"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(
            200, json={"signedURL": f"/object/sign/conversation-media/{path}?token=tok"}
        )

    _storage_settings(monkeypatch)
    monkeypatch.setattr(media_storage, "_transport", httpx.MockTransport(handler))
    url = await media_storage.create_signed_url(path)
    assert seen["path"] == f"/storage/v1/object/sign/conversation-media/{path}"
    assert seen["body"] == {"expiresIn": media_storage.SIGNED_URL_SECONDS}
    assert seen["auth"] == "Bearer srk"
    assert url == (
        f"https://proj.supabase.co/storage/v1/object/sign/conversation-media/{path}?token=tok"
    )


async def test_signed_url_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _storage_settings(monkeypatch)
    monkeypatch.setattr(
        media_storage,
        "_transport",
        httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "not_found"})),
    )
    with pytest.raises(ExternalIntegrationError):
        await media_storage.create_signed_url("t/c/m/0.jpg")


async def test_store_rejects_oversized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media_storage, "MAX_ATTACHMENT_BYTES", 3)
    with pytest.raises(ExternalIntegrationError):
        await media_storage.store_attachment(
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            message_id=INBOUND_MSG_ID,
            idx=0,
            content=b"1234",
            mime_type="image/png",
            kind="image",
        )


# ─── Worker: mensaje fijo sin grafo y adjuntos al ticket ─────────────────────


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from apps.api.services.inbound_media import MediaOutcome

    from tests.conftest import make_fake_bootstrap_connection
    from tests.test_inbound_worker import _agent, _job

    wm = "apps.api.services.inbound_worker"
    m: dict[str, Any] = {
        "get_tenant_configuration": AsyncMock(return_value=None),
        "inbound_already_answered": AsyncMock(return_value=False),
        "get_conversation": AsyncMock(
            return_value=make_conversation(channel="whatsapp", external_id="zconv-1")
        ),
        "get_inbound_message_contents": AsyncMock(return_value=[""]),
        "enforce_message_cap": AsyncMock(return_value=None),
        "process_inbound_media": AsyncMock(
            return_value=MediaOutcome(texts=[], fallback_kind="media_without_text")
        ),
        "flush_pending_messages": AsyncMock(return_value=0),
        "get_active_handoff_for_chat": AsyncMock(return_value=None),
        "forward_customer_message": AsyncMock(return_value=True),
        "get_active_integration": AsyncMock(return_value=None),
        "insert_message": AsyncMock(return_value=make_message(id=UUID(int=5))),
        "update_conversation_last_message": AsyncMock(),
        "deliver_to_customer": AsyncMock(return_value="delivered"),
    }
    for name, mock in m.items():
        monkeypatch.setattr(f"{wm}.{name}", mock)
    monkeypatch.setattr(f"{wm}.tenant_scope", make_fake_tenant_scope())
    monkeypatch.setattr(f"{wm}.bootstrap_connection", make_fake_bootstrap_connection())
    monkeypatch.setattr(f"{wm}._usage_recorder", MagicMock())
    m["agent"] = _agent()
    m["job"] = _job(channel="whatsapp")
    return m


async def _run(m: dict[str, Any]) -> str:
    from apps.api.services.inbound_worker import run_inbound_turn

    from tests.conftest import FakeSettings

    return await run_inbound_turn(m["job"], agent_service=m["agent"], settings=FakeSettings())


async def test_image_only_sends_fixed_message_without_graph(worker: dict[str, Any]) -> None:
    assert await _run(worker) == "media_fallback"
    worker["agent"].process_inbound.assert_not_awaited()
    msg = worker["insert_message"].await_args.kwargs
    assert msg["content"] == fixed_text("media_without_text", "es")
    assert msg["metadata"] == {"fixed_message": "media_without_text"}
    assert worker["deliver_to_customer"].await_args.kwargs["message_id"] == UUID(int=5)


async def test_media_goes_to_ticket_when_handoff_is_active(worker: dict[str, Any]) -> None:
    from apps.api.services.inbound_media import MediaOutcome

    from tests.test_handoff import _handoff

    photo = StoredAttachment(path="t/c/m/0.jpg", mime_type="image/jpeg", size=3, filename="0.jpg")
    worker["process_inbound_media"].return_value = MediaOutcome(
        texts=[], attachments=[photo], fallback_kind="media_without_text"
    )
    worker["get_active_handoff_for_chat"].return_value = _handoff()
    assert await _run(worker) == "handoff_forwarded"
    assert worker["forward_customer_message"].await_args.kwargs["attachments"] == [photo]
    worker["insert_message"].assert_not_awaited()  # sin mensaje fijo: lo lleva un humano


async def test_transcription_cost_is_recorded(worker: dict[str, Any]) -> None:
    from apps.api.services import inbound_worker
    from apps.api.services.inbound_media import MediaOutcome

    worker["process_inbound_media"].return_value = MediaOutcome(
        texts=["[Nota de voz] hola"], transcription_cost_usd=0.002
    )
    await _run(worker)
    inbound_worker._usage_recorder.record.assert_any_call(
        tenant_id=TENANT_ID, tokens_in=0, tokens_out=0, cost_usd=0.002
    )
    worker["agent"].process_inbound.assert_awaited_once()
    content = worker["agent"].process_inbound.await_args.kwargs["inbound_message_content"]
    assert content == "[Nota de voz] hola"
