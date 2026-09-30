"""Tests unitarios para services/pii.py."""

from __future__ import annotations

import hashlib
import json

import pytest
from apps.api.services.pii import hash_inputs, mask_free_text_pii, redact_inputs

SALT = "deadbeefdeadbeefdeadbeefdeadbeef"


class TestRedactInputs:
    def test_email_field_is_pseudonimizado(self) -> None:
        result = redact_inputs({"email": "ana@example.com"}, SALT)
        assert result["email"].startswith("<email:")
        assert "ana@example.com" not in result["email"]

    def test_customer_email_field_is_pseudonimizado(self) -> None:
        result = redact_inputs({"customer_email": "test@test.com"}, SALT)
        assert result["customer_email"].startswith("<email:")

    def test_email_mismo_valor_mismo_hash(self) -> None:
        r1 = redact_inputs({"email": "x@x.com"}, SALT)
        r2 = redact_inputs({"email": "x@x.com"}, SALT)
        assert r1["email"] == r2["email"]

    def test_email_distinto_salt_distinto_hash(self) -> None:
        r1 = redact_inputs({"email": "x@x.com"}, "salt1")
        r2 = redact_inputs({"email": "x@x.com"}, "salt2")
        assert r1["email"] != r2["email"]

    def test_phone_field_muestra_ultimos_4(self) -> None:
        result = redact_inputs({"phone": "+34 612 345 678"}, SALT)
        assert result["phone"] == "***-5678"

    def test_phone_corto_muestra_asteriscos(self) -> None:
        result = redact_inputs({"phone": "123"}, SALT)
        assert result["phone"] == "***"

    def test_name_field_muestra_iniciales(self) -> None:
        result = redact_inputs({"name": "Ana García López"}, SALT)
        assert result["name"] == "A. G. L."

    def test_first_name_field(self) -> None:
        result = redact_inputs({"first_name": "Carlos"}, SALT)
        assert result["first_name"] == "C."

    def test_address_fields_redactados(self) -> None:
        result = redact_inputs(
            {
                "address1": "Calle Jose Hierro 18, 3B",
                "city": "Madrid",
                "province": "Madrid",
                "country": "España",
                "zip_code": "28702",
            },
            SALT,
        )
        # La calle no deja rastro legible.
        assert result["address1"] == "<dirección>"
        assert "Jose Hierro" not in result["address1"]
        # El CP conserva el prefijo de provincia (ES) pero no el resto.
        assert result["zip_code"] == "28***"
        # Ciudad/provincia/país no identifican a la persona → se conservan.
        assert result["city"] == "Madrid"
        assert result["province"] == "Madrid"
        assert result["country"] == "España"

    def test_non_pii_fields_sin_cambio(self) -> None:
        result = redact_inputs(
            {"order_id": 1234, "note": "texto libre", "tags": ["a", "b"]},
            SALT,
        )
        assert result["order_id"] == 1234
        assert result["note"] == "texto libre"
        assert result["tags"] == ["a", "b"]

    def test_non_string_pii_field_sin_cambio(self) -> None:
        # Si el valor no es str, no se toca aunque el nombre sea pii
        result = redact_inputs({"email": None}, SALT)
        assert result["email"] is None

    def test_dict_vacio(self) -> None:
        assert redact_inputs({}, SALT) == {}

    def test_mezcla_pii_y_no_pii(self) -> None:
        result = redact_inputs(
            {"email": "a@b.com", "order_id": 42, "phone": "600111222"},
            SALT,
        )
        assert result["email"].startswith("<email:")
        assert result["order_id"] == 42
        assert result["phone"] == "***-1222"


class TestHashInputs:
    def test_hash_es_sha256_hex(self) -> None:
        inputs = {"order_id": 1, "email": "a@b.com"}
        result = hash_inputs(inputs)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_determinista(self) -> None:
        inputs = {"b": 2, "a": 1}
        assert hash_inputs(inputs) == hash_inputs(inputs)

    def test_hash_independiente_del_orden_de_claves(self) -> None:
        assert hash_inputs({"a": 1, "b": 2}) == hash_inputs({"b": 2, "a": 1})

    def test_hash_distinto_para_inputs_distintos(self) -> None:
        assert hash_inputs({"a": 1}) != hash_inputs({"a": 2})

    def test_hash_verifica_contra_sha256_manual(self) -> None:
        inputs = {"order_id": 99}
        canonical = json.dumps(inputs, sort_keys=True, default=str)
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        assert hash_inputs(inputs) == expected


class TestMaskFreeTextPii:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("soy juan.perez+1@gmail.com", "soy <email>"),
            ("móvil 612 345 678", "móvil ***-5678"),
            ("llámame al +34 612-345-678", "llámame al ***-5678"),
            ("tel 912345678.", "tel ***-5678."),
            # No son PII: pedidos, importes, tracking, códigos postales, IDs.
            ("pedido #1429 por 49.90 €", "pedido #1429 por 49.90 €"),
            ("tracking 17457464312088", "tracking 17457464312088"),
            ("CP 28013", "CP 28013"),
            ("pedido #612345678", "pedido #612345678"),
        ],
    )
    def test_masks_emails_and_phones_only(self, text: str, expected: str) -> None:
        assert mask_free_text_pii(text) == expected
