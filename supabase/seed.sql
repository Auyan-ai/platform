-- Auyan — Seeds para staging
-- Ejecutar DESPUÉS de la migración inicial.
--
-- Importante: este script inserta usuarios directamente en auth.users
-- con UUIDs fijos. Es aceptable en staging; en producción los usuarios
-- se crean vía Supabase Auth (signup / invite / admin API).
--
-- UUIDs fijos para poder referenciarlos:
--   Tenant:         11111111-1111-1111-1111-111111111111
--   Super admin:    22222222-2222-2222-2222-222222222222
--   Tenant agent:   33333333-3333-3333-3333-333333333333
--   End customer:   44444444-4444-4444-4444-444444444444
--   Conversation:   55555555-5555-5555-5555-555555555555

begin;

-- ============================================================
-- Tenant de prueba (ecommerce ficticio)
-- ============================================================
insert into tenants (id, slug, name, status)
values (
  '11111111-1111-1111-1111-111111111111',
  'lunaria',
  'Lunaria — Ecommerce de joyería',
  'active'
)
on conflict (id) do nothing;

-- ============================================================
-- Auth users (staff)
-- Password para ambos: "auyan-staging-2026" (hash bcrypt precomputado).
-- Cambiar tras el primer login.
-- ============================================================
-- GoTrue escanea estos cuatro tokens como `string` (no `*string`). Si quedan
-- NULL (que es lo que pasa cuando no se setean en el INSERT), el scan del
-- schema rompe con "Database error querying schema" en cada operación de auth.
-- Los seteamos a '' explícito.
insert into auth.users (
  id, instance_id, aud, role, email,
  encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data,
  confirmation_token, recovery_token,
  email_change_token_new, email_change,
  created_at, updated_at
) values
(
  '22222222-2222-2222-2222-222222222222',
  '00000000-0000-0000-0000-000000000000',
  'authenticated', 'authenticated',
  'super-admin@auyan.ai',
  crypt('auyan-staging-2026', gen_salt('bf')),
  now(),
  jsonb_build_object('role', 'super_admin'),
  jsonb_build_object('full_name', 'Auyan Super Admin'),
  '', '', '', '',
  now(), now()
),
(
  '33333333-3333-3333-3333-333333333333',
  '00000000-0000-0000-0000-000000000000',
  'authenticated', 'authenticated',
  'agente@lunaria.test',
  crypt('auyan-staging-2026', gen_salt('bf')),
  now(),
  jsonb_build_object(
    'role', 'tenant_admin',
    'tenant_id', '11111111-1111-1111-1111-111111111111'
  ),
  jsonb_build_object('full_name', 'María — Agente Lunaria'),
  '', '', '', '',
  now(), now()
);

-- ============================================================
-- Auth identities
-- GoTrue moderno requiere una identity por usuario para que el login
-- email/password funcione. provider_id debe ser el user_id como text
-- (no el email, aunque parezca natural), e identity_data necesita
-- email_verified=true para que la sesión se valide.
-- ============================================================
insert into auth.identities (
  id, user_id, identity_data, provider, provider_id,
  created_at, updated_at
)
select
  gen_random_uuid(),
  u.id,
  jsonb_build_object('sub', u.id::text, 'email', u.email, 'email_verified', true),
  'email',
  u.id::text,
  now(), now()
from auth.users u
where u.email in ('super-admin@auyan.ai', 'agente@lunaria.test');

-- ============================================================
-- Staff users (tabla public.users)
-- ============================================================
insert into users (id, tenant_id, email, full_name, role) values
(
  '22222222-2222-2222-2222-222222222222',
  null,
  'super-admin@auyan.ai',
  'Auyan Super Admin',
  'super_admin'
),
(
  '33333333-3333-3333-3333-333333333333',
  '11111111-1111-1111-1111-111111111111',
  'agente@lunaria.test',
  'María — Agente Lunaria',
  'tenant_admin'
);

-- ============================================================
-- Configuración del tenant
-- ============================================================
insert into tenant_configurations (
  tenant_id, agent_model, escalation_threshold,
  active_channels, branding, extra
) values (
  '11111111-1111-1111-1111-111111111111',
  'claude-sonnet-4-6',
  0.70,
  array['email', 'chat', 'whatsapp']::channel_type[],
  jsonb_build_object(
    'brand_name', 'Lunaria',
    'tone', 'cercano, elegante, breve',
    'primary_color', '#1a1a2e'
  ),
  jsonb_build_object(
    'business_hours', '09:00-18:00 CET',
    'currency', 'EUR'
  )
);

-- ============================================================
-- Prompt del sistema (versionado, activo)
-- ============================================================
insert into tenant_prompts (
  tenant_id, name, version, content, is_active, created_by
) values (
  '11111111-1111-1111-1111-111111111111',
  'system',
  1,
  $prompt$Eres el agente de atención al cliente de Lunaria, una marca de joyería online.

Tono: cercano, elegante, breve. Trata al cliente de "tú".

Tu misión: resolver dudas sobre pedidos, envíos, devoluciones, tallas y materiales con precisión y empatía. Si la consulta requiere acción humana (reembolso fuera de política, queja grave, pregunta legal, cliente muy molesto), escala a un agente humano explicando el motivo.

Reglas:
- Si no sabes algo con certeza, dilo y escala. Nunca inventes datos de pedidos, stock o políticas.
- Usa la knowledge base del tenant antes de responder sobre políticas o productos.
- Devoluciones aceptadas dentro de 30 días con producto sin uso.
- Envío gratis a partir de 60€ en España peninsular.
- Si el cliente pide hablar con un humano, escala sin discutir.

Idioma: responde en el idioma del cliente (por defecto, español).$prompt$,
  true,
  '22222222-2222-2222-2222-222222222222'
);

-- ============================================================
-- End customer de prueba
-- ============================================================
insert into end_customers (
  id, tenant_id, email, full_name, phone, external_id, metadata
) values (
  '44444444-4444-4444-4444-444444444444',
  '11111111-1111-1111-1111-111111111111',
  'laura.gomez@example.com',
  'Laura Gómez',
  '+34600123456',
  'shopify_cust_8821',
  jsonb_build_object(
    'lifetime_value_eur', 340.50,
    'orders_count', 4
  )
);

-- ============================================================
-- Conversación de prueba con 3 mensajes
-- ============================================================
insert into conversations (
  id, tenant_id, end_customer_id, channel,
  external_id, subject, status, last_message_at
) values (
  '55555555-5555-5555-5555-555555555555',
  '11111111-1111-1111-1111-111111111111',
  '44444444-4444-4444-4444-444444444444',
  'email',
  'postmark_msg_a1b2c3',
  '¿Cuándo llega mi pedido #8821?',
  'open',
  now()
);

insert into messages (
  tenant_id, conversation_id, role, direction,
  author_user_id, content, metadata, created_at
) values
(
  '11111111-1111-1111-1111-111111111111',
  '55555555-5555-5555-5555-555555555555',
  'customer', 'inbound', null,
  'Hola, hice el pedido #8821 hace 4 días y aún no me llega. ¿Podéis decirme cuándo lo recibo?',
  jsonb_build_object('email_from', 'laura.gomez@example.com'),
  now() - interval '20 minutes'
),
(
  '11111111-1111-1111-1111-111111111111',
  '55555555-5555-5555-5555-555555555555',
  'agent_ai', 'outbound', null,
  'Hola Laura, gracias por escribirnos. Tu pedido #8821 salió ayer con SEUR y el seguimiento marca entrega para mañana entre las 10:00 y las 14:00. ¿Necesitas algo más?',
  jsonb_build_object(
    'model', 'claude-sonnet-4-6',
    'prompt_tokens', 1820,
    'completion_tokens', 84,
    'cost_usd', 0.0073,
    'langfuse_trace_id', 'trace_demo_001'
  ),
  now() - interval '19 minutes'
),
(
  '11111111-1111-1111-1111-111111111111',
  '55555555-5555-5555-5555-555555555555',
  'customer', 'inbound', null,
  'Perfecto, muchas gracias.',
  jsonb_build_object('email_from', 'laura.gomez@example.com'),
  now() - interval '5 minutes'
);

-- ============================================================
-- Conversaciones adicionales para showcase (portfolio): cambio de
-- dirección y cancelación con aprobación pendiente, reembolso ya
-- aprobado, y una escalación. Todo ficticio, mismo tenant Lunaria.
-- ============================================================

insert into end_customers (id, tenant_id, email, full_name, phone, external_id, metadata) values
(
  'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1',
  '11111111-1111-1111-1111-111111111111',
  'marta.ruiz@example.com', 'Marta Ruiz', '+34611222333', 'shopify_cust_9034',
  jsonb_build_object('lifetime_value_eur', 89.00, 'orders_count', 1)
),
(
  'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2',
  '11111111-1111-1111-1111-111111111111',
  'javier.torres@example.com', 'Javier Torres', '+34622333444', 'shopify_cust_7745',
  jsonb_build_object('lifetime_value_eur', 45.00, 'orders_count', 1)
),
(
  'c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3',
  '11111111-1111-1111-1111-111111111111',
  'sofia.martin@example.com', 'Sofía Martín', '+34633444555', 'shopify_cust_6120',
  jsonb_build_object('lifetime_value_eur', 210.00, 'orders_count', 3)
),
(
  'd4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d4',
  '11111111-1111-1111-1111-111111111111',
  'carlos.vidal@example.com', 'Carlos Vidal', '+34644555666', 'shopify_cust_5502',
  jsonb_build_object('lifetime_value_eur', 610.00, 'orders_count', 6)
);

insert into conversations (id, tenant_id, end_customer_id, channel, external_id, subject, status, last_message_at) values
(
  'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a2',
  '11111111-1111-1111-1111-111111111111',
  'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1',
  'whatsapp', 'wa_msg_9034a', 'Cambio de dirección — pedido #9034', 'pending',
  now() - interval '10 minutes'
),
(
  'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b3',
  '11111111-1111-1111-1111-111111111111',
  'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2',
  'chat', 'chat_msg_7745a', 'Cancelación — pedido #7745', 'pending',
  now() - interval '35 minutes'
),
(
  'c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c4',
  '11111111-1111-1111-1111-111111111111',
  'c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3',
  'email', 'postmark_msg_6120a', 'Pulsera defectuosa — pedido #6120', 'resolved',
  now() - interval '2 hours'
),
(
  'd4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d5',
  '11111111-1111-1111-1111-111111111111',
  'd4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d4',
  'whatsapp', 'wa_msg_5502a', 'Segunda incidencia — pedido #5502', 'escalated',
  now() - interval '3 minutes'
);

insert into messages (tenant_id, conversation_id, role, direction, author_user_id, content, metadata, created_at) values
(
  '11111111-1111-1111-1111-111111111111', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a2',
  'customer', 'inbound', null,
  '¡Hola! Acabo de hacer el pedido #9034 pero me equivoqué en la dirección de envío. ¿Podéis cambiarla antes de que salga? Es urgente.',
  jsonb_build_object('whatsapp_from', '+34611222333'),
  now() - interval '14 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a2',
  'agent_ai', 'outbound', null,
  '¡Hola Marta! Claro, dime la dirección correcta y la actualizo ahora mismo. El pedido #9034 todavía no ha salido del almacén, así que llegamos a tiempo.',
  jsonb_build_object('model', 'claude-sonnet-4-6', 'prompt_tokens', 1640, 'completion_tokens', 52, 'cost_usd', 0.0061),
  now() - interval '13 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a2',
  'customer', 'inbound', null,
  'Perfecto, es Calle Alcalá 145, 3ºB, 28009 Madrid (antes puse un número mal).',
  jsonb_build_object('whatsapp_from', '+34611222333'),
  now() - interval '11 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a2',
  'agent_ai', 'outbound', null,
  'Ya tengo el cambio preparado — solo necesito la confirmación de un compañero antes de aplicarlo porque toca datos de envío ya confirmados. En cuanto se apruebe, te aviso. Gracias por la paciencia.',
  jsonb_build_object('model', 'claude-sonnet-4-6', 'prompt_tokens', 1710, 'completion_tokens', 61, 'cost_usd', 0.0067),
  now() - interval '10 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b3',
  'customer', 'inbound', null,
  'Buenas, quiero cancelar el pedido #7745, lo pedí sin querer por duplicado.',
  jsonb_build_object(), now() - interval '40 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b3',
  'agent_ai', 'outbound', null,
  'Hola Javier, sin problema. Veo el pedido #7745 (colgante de plata, 45€) — todavía está en preparación, así que se puede cancelar sin coste. ¿Confirmas que quieres cancelarlo?',
  jsonb_build_object('model', 'claude-sonnet-4-6', 'prompt_tokens', 1580, 'completion_tokens', 58, 'cost_usd', 0.0059),
  now() - interval '39 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b3',
  'customer', 'inbound', null,
  'Sí, confirmado, cancélalo por favor.',
  jsonb_build_object(), now() - interval '37 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b3',
  'agent_ai', 'outbound', null,
  'Hecho por mi parte — la cancelación de un pedido ya en preparación necesita el visto bueno de un compañero antes de procesarse, así evitamos duplicar reembolsos. Te confirmo en cuanto esté aprobada, normalmente en minutos.',
  jsonb_build_object('model', 'claude-sonnet-4-6', 'prompt_tokens', 1690, 'completion_tokens', 66, 'cost_usd', 0.0065),
  now() - interval '35 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c4',
  'customer', 'inbound', null,
  'Hola, la pulsera que me llegó (pedido #6120) tiene el cierre roto, no se puede usar. Quiero un reembolso.',
  jsonb_build_object('email_from', 'sofia.martin@example.com'), now() - interval '2 hours 10 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c4',
  'agent_ai', 'outbound', null,
  'Vaya, lo sentimos mucho Sofía. Con una foto del defecto no haría falta ni devolver la pieza — si nos la envías, te tramito el reembolso completo (39€) hoy mismo.',
  jsonb_build_object('model', 'claude-sonnet-4-6', 'prompt_tokens', 1550, 'completion_tokens', 55, 'cost_usd', 0.0057),
  now() - interval '2 hours 8 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c4',
  'customer', 'inbound', null,
  'Aquí tienes la foto. Gracias por la rapidez.',
  jsonb_build_object('email_from', 'sofia.martin@example.com', 'attachments', 1), now() - interval '2 hours 3 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c4',
  'agent_ai', 'outbound', null,
  'Recibido, se ve claramente el cierre partido. Reembolso de 39€ aprobado y procesado a tu método de pago original — en 3-5 días hábiles lo verás reflejado. Sentimos las molestias.',
  jsonb_build_object('model', 'claude-sonnet-4-6', 'prompt_tokens', 1620, 'completion_tokens', 60, 'cost_usd', 0.0063),
  now() - interval '2 hours'
);

-- Mensajes de Carlos (escalación): el primero necesita id explícito para que
-- escalations.triggered_by_message_id lo pueda referenciar.
insert into messages (id, tenant_id, conversation_id, role, direction, author_user_id, content, metadata, created_at) values
(
  'dddddddd-dddd-dddd-dddd-ddddddddddd4',
  '11111111-1111-1111-1111-111111111111', 'd4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d5',
  'customer', 'inbound', null,
  'Es la SEGUNDA vez que me llega un pedido roto. Pedido #5502. Esto es una tomadura de pelo, quiero que me devolváis el dinero Y una compensación, ya no confío en la marca.',
  jsonb_build_object('whatsapp_from', '+34644555666'),
  now() - interval '5 minutes'
);

insert into messages (tenant_id, conversation_id, role, direction, author_user_id, content, metadata, created_at) values
(
  '11111111-1111-1111-1111-111111111111', 'd4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d5',
  'agent_ai', 'outbound', null,
  'Entiendo perfectamente tu frustración, Carlos, y sentimos mucho que se repita. Voy a pasar tu caso directamente a un compañero del equipo para que revise una compensación — no es algo que yo pueda decidir sola. Te contactará hoy mismo.',
  jsonb_build_object('model', 'claude-sonnet-4-6', 'prompt_tokens', 1740, 'completion_tokens', 70, 'cost_usd', 0.0071),
  now() - interval '4 minutes'
),
(
  '11111111-1111-1111-1111-111111111111', 'd4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d5',
  'customer', 'inbound', null,
  'Más vale, porque si no cancelo la cuenta.',
  jsonb_build_object('whatsapp_from', '+34644555666'),
  now() - interval '3 minutes'
);

-- ============================================================
-- Aprobaciones pendientes (cola para el dashboard) y una aprobada
-- ============================================================
insert into pending_approvals (
  tenant_id, conversation_id, skill_slug, skill_tier,
  inputs_raw, inputs_redacted, aop_slug, aop_version, status
) values
(
  '11111111-1111-1111-1111-111111111111', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a2',
  'shopify.update_shipping_address', 'L2',
  jsonb_build_object('order_id', '9034', 'new_address', 'Calle Alcalá 145, 3ºB, 28009 Madrid'),
  jsonb_build_object('order_id', '9034', 'new_address', 'Calle Alcalá 145, 3ºB, 28*** Madrid'),
  'shopify_cambio_direccion', 1, 'pending'
),
(
  '11111111-1111-1111-1111-111111111111', 'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b3',
  'shopify.cancel_order', 'L3',
  jsonb_build_object('order_id', '7745', 'reason', 'Pedido duplicado, solicitado por el cliente'),
  jsonb_build_object('order_id', '7745', 'reason', 'Pedido duplicado, solicitado por el cliente'),
  'shopify_cancelaciones', 1, 'pending'
);

insert into pending_approvals (
  tenant_id, conversation_id, skill_slug, skill_tier,
  inputs_raw, inputs_redacted, aop_slug, aop_version, status,
  reviewed_by, reviewed_at
) values (
  '11111111-1111-1111-1111-111111111111', 'c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c4',
  'shopify.refund_partial', 'L3',
  jsonb_build_object('order_id', '6120', 'amount_eur', 39.00, 'reason', 'Cierre de pulsera defectuoso, foto verificada'),
  jsonb_build_object('order_id', '6120', 'amount_eur', 39.00, 'reason', 'Cierre de pulsera defectuoso, foto verificada'),
  'shopify_reembolso', 1, 'approved',
  '33333333-3333-3333-3333-333333333333', now() - interval '2 hours 1 minute'
);

-- ============================================================
-- Escalación pendiente (segunda incidencia, cliente muy molesto)
-- ============================================================
insert into escalations (
  tenant_id, conversation_id, reason, triggered_by_message_id, status
) values (
  '11111111-1111-1111-1111-111111111111', 'd4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d5',
  'Cliente exige compensación fuera de política + segunda incidencia con el mismo defecto + tono muy molesto (amenaza con cancelar cuenta).',
  'dddddddd-dddd-dddd-dddd-ddddddddddd4',
  'pending'
);

commit;
