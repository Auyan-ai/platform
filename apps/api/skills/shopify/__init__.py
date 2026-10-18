"""Side-effect imports — registra todas las skills de Shopify en `SkillRegistry`.

Cada submódulo se decora con `@SkillRegistry.register` a nivel módulo, así que
basta con importarlos para que queden disponibles. Agregar una skill nueva =
agregar una línea acá.
"""

from apps.api.skills.shopify import (  # noqa: F401
    add_order_note,
    cancel_order,
    get_order_status,
    get_product_info,
    get_shop_policies,
    list_my_orders,
    refund_partial,
    start_exchange,
    start_return,
    tag_order,
    update_shipping_address,
)
