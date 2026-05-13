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
);

-- ============================================================
-- Auth users (staff)
-- Password para ambos: "auyan-staging-2026" (hash bcrypt precomputado).
-- Cambiar tras el primer login.
-- ============================================================
insert into auth.users (
  id, instance_id, aud, role, email,
  encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data,
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
    'role', 'tenant_agent',
    'tenant_id', '11111111-1111-1111-1111-111111111111'
  ),
  jsonb_build_object('full_name', 'María — Agente Lunaria'),
  now(), now()
);

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
  'tenant_agent'
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

commit;
