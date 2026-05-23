"""Cifrado/descifrado AES-256-GCM para credentials de integraciones por tenant.

Diseño:
- Clave maestra de 32 bytes configurada en INTEGRATIONS_SECRET_KEY (hex, 64 chars).
- Nonce de 12 bytes aleatorio generado por cifrado — nunca reutilizado.
- Formato en DB: nonce(12 bytes) || ciphertext+tag (N+16 bytes).
- El GCM tag (16 bytes) lo maneja AESGCM internamente — protege contra tampering.

La key se pasa como argumento (no se lee de os.environ aquí) para facilitar
tests y permitir rotación de keys sin reiniciar el proceso.

Helper get_integration_crypto_key() extrae la key de Settings y la valida.
"""

from __future__ import annotations

import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12


def encrypt_credentials(plaintext: bytes, key: bytes) -> bytes:
    """Cifra plaintext con AES-256-GCM.

    Retorna nonce(12) + ciphertext (con GCM tag de 16 bytes al final).
    """
    if len(key) != 32:
        raise ValueError("integration crypto key must be 32 bytes")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_credentials(ciphertext: bytes, key: bytes) -> bytes:
    """Descifra y verifica integridad (GCM tag).

    Lanza cryptography.exceptions.InvalidTag si el ciphertext fue manipulado.
    """
    if len(key) != 32:
        raise ValueError("integration crypto key must be 32 bytes")
    if len(ciphertext) < _NONCE_BYTES + 16:
        raise ValueError("ciphertext too short — corrupt or wrong format")
    nonce, data = ciphertext[:_NONCE_BYTES], ciphertext[_NONCE_BYTES:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, data, None)


def get_integration_crypto_key(settings: object) -> bytes:
    """Extrae y valida la clave de cifrado desde Settings.

    Acepta cualquier objeto con atributo integrations_secret_key (SecretStr | None).
    Lanza RuntimeError si no está configurada o tiene longitud incorrecta.
    """
    secret = getattr(settings, "integrations_secret_key", None)
    if secret is None:
        raise RuntimeError(
            "INTEGRATIONS_SECRET_KEY not configured — "
            "generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    # Soporta pydantic SecretStr (.get_secret_value()) y str planos (tests).
    raw: str = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError("INTEGRATIONS_SECRET_KEY must be a valid hex string") from exc
    if len(key) != 32:
        raise ValueError(
            f"INTEGRATIONS_SECRET_KEY must be 32 bytes (64 hex chars), got {len(key)}"
        )
    return key
