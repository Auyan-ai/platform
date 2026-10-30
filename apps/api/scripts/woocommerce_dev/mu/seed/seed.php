<?php
/* Siembra la tienda de prueba. Idempotente: si la clave ya existe, no vuelve a sembrar. */
require '/wordpress/wp-load.php';
global $wpdb;

$ck = 'ck_auyandevlocal000000000000000000000000000';
$cs = 'cs_auyandevlocal000000000000000000000000000';
$keys = $wpdb->prefix . 'woocommerce_api_keys';
if ($wpdb->get_var($wpdb->prepare("SELECT key_id FROM $keys WHERE description = %s", 'auyan-dev'))) {
    echo json_encode(['seeded' => false, 'reason' => 'already_seeded']);
    exit;
}

update_option('woocommerce_currency', 'EUR');
update_option('blogname', 'Tienda Prueba Auyan');
update_option('blogdescription', 'Moda sostenible');
$wpdb->insert($keys, [
    'user_id' => 1, 'description' => 'auyan-dev', 'permissions' => 'read_write',
    'consumer_key' => wc_api_hash($ck), 'consumer_secret' => $cs, 'truncated_key' => substr($ck, -7),
]);

$mk = function ($name, $price, $stock, $sku) {
    $p = new WC_Product_Simple();
    $p->set_name($name); $p->set_regular_price($price);
    $p->set_manage_stock(true); $p->set_stock_quantity($stock); $p->set_sku($sku);
    $p->set_description("Descripción de $name, algodón orgánico.");
    $p->save();
    return $p;
};
$a = $mk('Camiseta Lino Azul', '29.90', 50, 'CAM-AZ');
$b = $mk('Pantalón Chino Arena', '59.00', 0, 'PAN-AR');
$attr = new WC_Product_Attribute();
$attr->set_name('Talla'); $attr->set_options(['S', 'M', 'L']); $attr->set_visible(true); $attr->set_variation(true);
$v = new WC_Product_Variable();
$v->set_name('Sudadera Orgánica'); $v->set_attributes([$attr]); $v->save();
foreach (['S' => 5, 'M' => 0, 'L' => 3] as $t => $s) {
    $var = new WC_Product_Variation();
    $var->set_parent_id($v->get_id()); $var->set_attributes(['talla' => $t]);
    $var->set_regular_price('45.00'); $var->set_manage_stock(true); $var->set_stock_quantity($s);
    $var->save();
}

$order = function ($email, $phone, $items, $method, $status) {
    $o = wc_create_order();
    foreach ($items as [$p, $q]) { $o->add_product($p, $q); }
    $addr = ['first_name' => 'Ana', 'last_name' => 'García', 'email' => $email, 'phone' => $phone,
        'address_1' => 'Calle Mayor 1', 'city' => 'Madrid', 'postcode' => '28013', 'state' => 'M', 'country' => 'ES'];
    $o->set_address($addr, 'billing');
    unset($addr['email']);
    $o->set_address($addr, 'shipping');
    $o->set_payment_method($method);
    $o->calculate_totals();
    if ($status === 'paid') { $o->payment_complete('txn_seed_' . $o->get_id()); } else { $o->set_status($status); }
    $o->save();
    return $o->get_id();
};
$ids = [
    $order('ana@example.com', '+34600111222', [[$a, 2]], 'auyan_test', 'paid'),
    $order('ana@example.com', '+34600111222', [[$a, 1]], 'cod', 'processing'),
    $order('luis@example.com', '612333444', [[$a, 1]], 'bacs', 'on-hold'),
    $order('ana@example.com', '+34600111222', [[$a, 1]], 'auyan_test', 'paid'),
];
$done = wc_get_order($ids[3]); $done->set_status('completed'); $done->save();

/* Las páginas de políticas que WordPress y WooCommerce crean como borrador, publicadas. */
foreach ([get_option('woocommerce_refund_returns_page_id'), get_option('wp_page_for_privacy_policy')] as $page) {
    if ($page) { wp_update_post(['ID' => (int) $page, 'post_status' => 'publish']); }
}
wp_insert_post(['post_type' => 'page', 'post_status' => 'publish', 'post_title' => 'Envíos', 'post_name' => 'envios',
    'post_content' => '<p>Enviamos en 24-48 horas laborables a toda la península. Gratis a partir de 50 euros.</p>']);
$faq = wp_insert_post(['post_type' => 'page', 'post_status' => 'publish', 'post_title' => 'Preguntas frecuentes', 'post_name' => 'faq',
    'post_content' => '<h2>¿Cuánto tarda el envío?</h2><p>Enviamos en 24-48 horas laborables a toda la península. Baleares y Canarias de 3 a 5 días. El envío es gratis a partir de 50 euros.</p><h2>¿Puedo cambiar la talla?</h2><p>Sí, tienes 30 días desde la entrega para pedir un cambio de talla escribiéndonos a hola@tiendaprueba.test.</p>']);

echo json_encode(['seeded' => true, 'orders' => $ids, 'products' => [$a->get_id(), $b->get_id(), $v->get_id()], 'faq' => $faq]);
