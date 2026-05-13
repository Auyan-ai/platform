"""Tests del HMAC-SHA256 verifier de webhooks."""

from __future__ import annotations

import hashlib
import hmac

from apps.api.routers.webhooks import _verify_signature


SECRET = "test-shared-secret"
BODY = b'{"hello":"world"}'


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestVerifySignature:
    def test_valid_signature_passes(self) -> None:
        assert _verify_signature(BODY, _sign(BODY), SECRET) is True

    def test_tampered_body_fails(self) -> None:
        good_sig = _sign(BODY)
        tampered = BODY + b" extra"
        assert _verify_signature(tampered, good_sig, SECRET) is False

    def test_wrong_secret_fails(self) -> None:
        sig_with_other_secret = _sign(BODY, secret="other-secret")
        assert _verify_signature(BODY, sig_with_other_secret, SECRET) is False

    def test_missing_prefix_fails(self) -> None:
        # Header sin "sha256=" debe rechazarse
        raw_hex = hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        assert _verify_signature(BODY, raw_hex, SECRET) is False

    def test_empty_header_fails(self) -> None:
        assert _verify_signature(BODY, "", SECRET) is False

    def test_malformed_header_fails(self) -> None:
        assert _verify_signature(BODY, "sha256=not-hex-content", SECRET) is False

    def test_empty_body_valid_signature(self) -> None:
        empty = b""
        assert _verify_signature(empty, _sign(empty), SECRET) is True
