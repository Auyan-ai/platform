"""IntegrationRegistry — registro central de todos los adapters de integración.

Sigue el mismo patrón que SkillRegistry: class-variable singleton, decorator
@IntegrationRegistry.register(kind, provider), lookup O(1) por (kind, provider).

Uso típico en un adapter:

    @IntegrationRegistry.register(kind="helpdesk", provider="chatwoot")
    class ChatwootAdapter:
        ...

Lookup en el service layer:

    adapter_class = IntegrationRegistry.get("helpdesk", "chatwoot")
    adapter = adapter_class()
    result = await adapter.send_outbound(ctx, ...)
"""

from __future__ import annotations

from typing import Any, ClassVar


class IntegrationRegistry:
    """Singleton de clase que mapea (kind, provider) → clase de adapter."""

    _registry: ClassVar[dict[tuple[str, str], type[Any]]] = {}

    @classmethod
    def register(cls, kind: str, provider: str):  # type: ignore[return]
        """Decorator que registra un adapter para (kind, provider).

        Uso: @IntegrationRegistry.register(kind="helpdesk", provider="gorgias")
        """

        def decorator(adapter_class: type[Any]) -> type[Any]:
            cls._registry[(kind, provider)] = adapter_class
            return adapter_class

        return decorator

    @classmethod
    def get(cls, kind: str, provider: str) -> type[Any]:
        """Devuelve la clase del adapter. Lanza ValueError si no está registrado."""
        key = (kind, provider)
        if key not in cls._registry:
            raise ValueError(f"unknown_integration: {kind}/{provider}")
        return cls._registry[key]

    @classmethod
    def list_for_kind(cls, kind: str) -> list[tuple[str, type[Any]]]:
        """Devuelve [(provider, adapter_class)] para el kind dado, ordenados por provider."""
        return sorted(
            [(p, c) for (k, p), c in cls._registry.items() if k == kind],
            key=lambda x: x[0],
        )

    @classmethod
    def all_registered(cls) -> list[tuple[str, str, type[Any]]]:
        """Devuelve [(kind, provider, adapter_class)] de todos los registros."""
        return [(k, p, c) for (k, p), c in cls._registry.items()]

    @classmethod
    def _reset(cls) -> None:
        """Limpia el registry. Solo para tests — no llamar en producción."""
        cls._registry.clear()
