<?php
/*
 * Solo desarrollo y CI. Nunca en una tienda real.
 *
 * - WooCommerce exige HTTPS para Basic auth en la REST API y Playground sirve HTTP.
 * - Pasarela `auyan_test` que reembolsa por API (la ruta automatic). Un motivo de reembolso
 *   que contenga FAIL la hace rechazar, como una pasarela real que deniega.
 * - Numeración secuencial simulada: un pedido con la meta `_auyan_order_number` la usa como
 *   número visible y la búsqueda la encuentra, como el plugin Sequential Order Numbers.
 */
/*
 * Sin cron, sin el runner asíncrono de Action Scheduler y sin HTTP saliente: en Playground
 * cada uno añade segundos a cada petición, y la tienda de prueba no los necesita.
 */
if (!defined('DISABLE_WP_CRON')) { define('DISABLE_WP_CRON', true); }
add_filter('action_scheduler_allow_async_request_runner', '__return_false');
add_filter('pre_http_request', fn ($pre, $args, $url) => new WP_Error('http_blocked', "Playground de Auyan sin HTTP saliente: $url"), 10, 3);

if (isset($_SERVER['REQUEST_URI']) && (str_contains($_SERVER['REQUEST_URI'], '/wp-json/') || str_contains($_SERVER['REQUEST_URI'], 'rest_route='))) {
    $_SERVER['HTTPS'] = 'on';
}

add_action('plugins_loaded', function () {
    if (!class_exists('WC_Payment_Gateway')) { return; }
    class Auyan_Test_Gateway extends WC_Payment_Gateway {
        public function __construct() {
            $this->id = 'auyan_test';
            $this->method_title = 'Auyan test card';
            $this->title = 'Tarjeta (test)';
            $this->enabled = 'yes';
            $this->supports = ['products', 'refunds'];
        }
        public function process_payment($order_id) {
            wc_get_order($order_id)->payment_complete('txn_' . $order_id);
            return ['result' => 'success'];
        }
        public function process_refund($order_id, $amount = null, $reason = '') {
            if (str_contains((string) $reason, 'FAIL')) {
                return new WP_Error('gateway_declined', 'Declined by test gateway');
            }
            return true;
        }
    }
    add_filter('woocommerce_payment_gateways', function ($g) { $g[] = 'Auyan_Test_Gateway'; return $g; });
});

add_filter('woocommerce_order_number', function ($number, $order) {
    $custom = $order->get_meta('_auyan_order_number');
    return $custom !== '' ? (string) $custom : $number;
}, 10, 2);
add_filter('woocommerce_order_table_search_query_meta_keys', fn ($keys) => array_merge($keys, ['_auyan_order_number']));
add_filter('woocommerce_shop_order_search_fields', fn ($fields) => array_merge($fields, ['_auyan_order_number']));
