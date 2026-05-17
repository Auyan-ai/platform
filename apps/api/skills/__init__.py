"""Paquete de skills del agente.

Importar este paquete dispara los side-effect imports de cada integración,
que a su vez registran sus skills en `SkillRegistry` vía `@register`.

Para agregar una integración nueva: crear el subpaquete y agregarlo acá.
"""

from apps.api.skills import shopify  # noqa: F401
