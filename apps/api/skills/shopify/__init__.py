"""Side-effect imports — registra todas las skills de Shopify en `SkillRegistry`.

Cada submódulo se decora con `@SkillRegistry.register` a nivel módulo, así que
basta con importarlos para que queden disponibles. Agregar una skill nueva =
agregar una línea acá.
"""

from apps.api.skills.shopify import (  # noqa: F401
    add_order_note,
    cancel_order,
    get_customer_history,
    get_order_by_email,
    get_order_status,
    get_product_info,
    get_shop_policies,
    refund_partial,
    start_return,
    tag_order,
    update_shipping_address,
)
