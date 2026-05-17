"""Side-effect imports — registra las skills L1 de Shopify en `SkillRegistry`.

Cada submódulo se decora con `@SkillRegistry.register` a nivel módulo, así que
basta con importarlos para que queden disponibles. Agregar una skill nueva =
agregar una línea acá.
"""

from apps.api.skills.shopify import (  # noqa: F401
    get_customer_history,
    get_order_by_email,
    get_order_status,
    get_product_info,
    get_shop_policies,
)
