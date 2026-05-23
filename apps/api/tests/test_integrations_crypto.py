"""Tests unitarios para services/integrations_crypto.py."""

from __future__ import annotations

import secrets

import pytest
from apps.api.services.integrations_crypto import (
    decrypt_credentials,
    encrypt_credentials,
    get_integration_crypto_key,
)

# Clave de 32 bytes fija para tests.
TEST_KEY = bytes.fromhex("a" * 64)


class TestEncryptDecrypt:
    def test_roundtrip_basico(self) -> None:
        plaintext = b"api_key=supersecret&token=abc123"
        ciphertext = encrypt_credentials(plaintext, TEST_KEY)
        result = decrypt_credentials(ciphertext, TEST_KEY)
        assert result == plaintext

    def test_roundtrip_dict_json(self) -> None:
        import json

        data = {"api_key": "gk_live_xyz", "subdomain": "acme", "scopes": ["read", "write"]}
        plaintext = json.dumps(data).encode()
        ciphertext = encrypt_credentials(plaintext, TEST_KEY)
        result = decrypt_credentials(ciphertext, TEST_KEY)
        assert json.loads(result) == data

    def test_roundtrip_bytes_vacios(self) -> None:
        plaintext = b""
        ciphertext = encrypt_credentials(plaintext, TEST_KEY)
        result = decrypt_credentials(ciphertext, TEST_KEY)
        assert result == plaintext

    def test_dos_cifrados_del_mismo_plaintext_son_distintos(self) -> None:
        plaintext = b"same plaintext"
        ct1 = encrypt_credentials(plaintext, TEST_KEY)
        ct2 = encrypt_credentials(plaintext, TEST_KEY)
        # Nonces distintos → ciphertexts distintos
        assert ct1 != ct2

    def test_ciphertext_tiene_al_menos_nonce_mas_tag(self) -> None:
        plaintext = b"x"
        ciphertext = encrypt_credentials(plaintext, TEST_KEY)
        # 12 bytes nonce + 1 byte plaintext + 16 bytes GCM tag = 29
        assert len(ciphertext) == 29

    def test_key_incorrecta_falla_verificacion(self) -> None:
        from cryptography.exceptions import InvalidTag

        plaintext = b"secret"
        ciphertext = encrypt_credentials(plaintext, TEST_KEY)
        wrong_key = bytes.fromhex("b" * 64)
        with pytest.raises(InvalidTag):
            decrypt_credentials(ciphertext, wrong_key)

    def test_ciphertext_manipulado_falla_verificacion(self) -> None:
        from cryptography.exceptions import InvalidTag

        plaintext = b"secret"
        ciphertext = bytearray(encrypt_credentials(plaintext, TEST_KEY))
        # Flippea un bit en el ciphertext (después del nonce)
        ciphertext[15] ^= 0xFF
        with pytest.raises(InvalidTag):
            decrypt_credentials(bytes(ciphertext), TEST_KEY)

    def test_key_longitud_incorrecta_lanza_error(self) -> None:
        bad_key = b"short"
        with pytest.raises(ValueError, match="32 bytes"):
            encrypt_credentials(b"data", bad_key)

    def test_decrypt_key_longitud_incorrecta_lanza_error(self) -> None:
        ciphertext = encrypt_credentials(b"data", TEST_KEY)
        with pytest.raises(ValueError, match="32 bytes"):
            decrypt_credentials(ciphertext, b"short")

    def test_decrypt_ciphertext_demasiado_corto(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            decrypt_credentials(b"tiny", TEST_KEY)


class TestGetIntegrationCryptoKey:
    def test_extrae_key_desde_objeto_con_get_secret_value(self) -> None:
        class FakeSecret:
            def get_secret_value(self) -> str:
                return "a" * 64

        class FakeSettings:
            integrations_secret_key = FakeSecret()

        key = get_integration_crypto_key(FakeSettings())
        assert key == bytes.fromhex("a" * 64)
        assert len(key) == 32

    def test_extrae_key_desde_str_plano(self) -> None:
        class FakeSettings:
            integrations_secret_key = "b" * 64

        key = get_integration_crypto_key(FakeSettings())
        assert len(key) == 32

    def test_lanza_si_no_configurada(self) -> None:
        class FakeSettings:
            integrations_secret_key = None

        with pytest.raises(RuntimeError, match="INTEGRATIONS_SECRET_KEY not configured"):
            get_integration_crypto_key(FakeSettings())

    def test_lanza_si_hex_invalido(self) -> None:
        class FakeSettings:
            integrations_secret_key = "ZZZZ"

        with pytest.raises(ValueError, match="valid hex"):
            get_integration_crypto_key(FakeSettings())

    def test_lanza_si_longitud_incorrecta(self) -> None:
        class FakeSettings:
            integrations_secret_key = "ab" * 16  # 16 bytes, no 32

        with pytest.raises(ValueError, match="32 bytes"):
            get_integration_crypto_key(FakeSettings())

    def test_roundtrip_con_settings_reales(self) -> None:
        key_hex = secrets.token_hex(32)

        class FakeSettings:
            integrations_secret_key = key_hex

        key = get_integration_crypto_key(FakeSettings())
        plaintext = b"test payload"
        ciphertext = encrypt_credentials(plaintext, key)
        assert decrypt_credentials(ciphertext, key) == plaintext
