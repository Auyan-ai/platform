# Plan — Sistema de Onboarding end-to-end

_Cerrado vía /grill-me (sesión 56, 2026-05-31). Objetivo: dejar el onboarding listo end-to-end, productizado y validado en una tienda Shopify real, para empezar a vender._

---

## 1. Contexto y objetivo

Auyan es un **Managed AI Service** fully-managed para CX e-commerce. Hoy **no existe ningún path de creación** de tenants ni usuarios: todo se hizo a mano por SQL + Supabase Auth dashboard. La meta es construir el onboarding completo que tendremos con clientes reales, con la **menor fricción posible**, **alta calidad** y **sin sobreingeniería**, y dogfoodearlo en una tienda Shopify nueva (completamente poblada) como primer caso real.

**Posicionamiento que define el modelo:** somos managed (más cerca de Decagon/Sierra que de Gorgias self-serve). El cliente nos concede acceso a su información en un onboarding guiado, **no** en un signup público anónimo.

---

## 2. Decisiones cerradas (grill-me)

| # | Decisión | Elegido |
|---|---|---|
| 1 | Dónde vive el provisioning | **Service server-side** (usa `supabase_service_role_key`) + endpoint super_admin + botón "Nuevo cliente" en dashboard. Reusable y auditable. |
| 2 | Modelo de entrada | **Portal por invitación / magic link** (no signup público). Ventas cierra → super_admin crea tenant → cliente recibe magic link. |
| 3 | Tier trial / facturación menor | **Diferido.** Solo se añade columna `plan_tier` (`founding`/`standard`/`trial`) como semilla. El self-serve trial se diseña/construye en Bloque 2+. |
| 4 | Invite / primer login | **Supabase invite + magic link** (Admin API `inviteUserByEmail`/`generateLink`). Sin passwords nuestros. Email vía SMTP de Supabase ahora; migrable a Postmark. |
| 5 | Acceso Shopify | **Custom app token pegado en el portal** (TLS + cifrado en `tenant_integrations`). Reusa el modelo de token estático actual; cero build de OAuth Shopify. |
| 6 | Lifecycle del agente | **Auto hasta `building`, resto AIDE-gated.** `initial→discovery` (invite) y `discovery→building` (onboarding enviado + integraciones + KB) automáticos; `building→shadow→ramping→active` los aprueba el AIDE. |
| 7 | Webhook inbound Chatwoot | **Auto vía API** tras pegar el token (backend crea el webhook → `/webhooks/chatwoot` con secreto HMAC). |
| 8 | KB inicial | **Drop-zone/URLs (reuso) + Shopify auto-import (build ahora).** Jalar policies/pages/blogs/articles de la tienda → cola `pending_review`. |
| 9 | Starter del agente | **Plantilla starter e-commerce ES** (AOPs típicos + esqueleto playbook + schema facts) clonada al crear el tenant; el AIDE afina. |
| 10 | Secuencia de trabajo | **Construir productizado y dogfood en la tienda real** pieza por pieza. Sin script desechable. Más lento, pero queda listo end-to-end. |

---

## 3. Arquitectura — qué se reusa vs qué es nuevo

### Ya existe (reusar)
- `tenants`, `users` (FK a `auth.users`), `internal_users` + `tenant_assignments`, `tenant_onboarding` (+ enum `agent_lifecycle_state`), `tenant_integrations` (cifrado), `tenant_knowledge_submissions` (guarda texto extraído / URL), `tenant_playbook`, `tenant_facts`.
- **Wizard de onboarding de 9 pasos** ([OnboardingWizard.tsx](../apps/web/components/onboarding/OnboardingWizard.tsx)) con RLS por tenant.
- **OAuth helpdesks** ya construido: `oauth_gorgias.py`, `oauth_zendesk.py` (state HMAC anti-CSRF, code→token, guardado cifrado).
- **Cliente Shopify** ([shopify.py](../apps/api/integrations/shopify.py)) con `get_policies()` (políticas legales de la tienda) — quick win para el import.
- Scripts: `configure_staging_integrations.py`, `seed_test_aops.py`, `seed_kb.py`.
- `supabase_service_role_key` ya en config (hoy **sin usar**) — es la llave del provisioning.

### Nuevo a construir
- **Provisioning service** (server-side, service_role): crea en una transacción `auth.users` (invite) + `tenants` + `public.users` (role `tenant_admin`) + `tenant_onboarding` + `tenant_assignment` (AIDE primario) + clona starter AOPs/playbook/facts. Lifecycle `initial`.
- **Endpoint super_admin** `POST /tenants` (provisioning) + UI "Nuevo cliente" en el dashboard super_admin.
- **Portal del cliente**: extender el wizard con (a) subida de docs/URLs → `pending_review`, (b) campo seguro de token Shopify + "Conectar", (c) campo token Chatwoot + auto-creación de webhook, (d) botones "Conectar" Gorgias/Zendesk (OAuth existente).
- **Shopify content auto-import**: métodos nuevos en el cliente (`list_pages`, `list_blogs`, `list_articles`) + `get_policies()`; detección de páginas relevantes (faq/devoluciones/envíos/garantía/términos/privacidad); HTML→markdown; insertar como submissions `pending_review`.
- **Columna `plan_tier`** en `tenants`.
- **Transiciones automáticas** de lifecycle `initial→discovery→building` por checklist.
- **Starter pack** de AOPs e-commerce ES (clonable).

---

## 4. Flujo end-to-end

**super_admin / AIDE (nosotros):**
1. Ventas cierra → en el dashboard, "Nuevo cliente": nombre comercial, slug, email + nombre del `tenant_admin`, `plan_tier`.
2. El provisioning service crea todo server-side, asigna AIDE primario, clona starter del agente, deja lifecycle `initial` y dispara el invite. → lifecycle pasa a `discovery`.

**Cliente (`tenant_admin`):**
3. Recibe magic link → entra al portal (sin password).
4. Completa el wizard de 9 pasos (datos, brand voice, facts, etc.).
5. **Concede acceso Shopify**: crea custom app en su admin, pega el Admin API token → backend valida (`shop.json`) y dispara el **auto-import** de contenido a `pending_review`.
6. **Conecta helpdesk**: Chatwoot (pega token → auto-webhook) o Gorgias/Zendesk (botón OAuth).
7. Sube docs/URLs extra → `pending_review`.
8. Envía el onboarding. → lifecycle pasa a `building` cuando se cumple el checklist (onboarding enviado + ≥1 integración commerce + ≥1 helpdesk + KB con contenido).

**AIDE (nosotros), gating manual de calidad:**
9. Afina AOPs/playbook/facts sobre la plantilla; aprueba la KB en `pending_review`.
10. `building → shadow` (agente corre pero no envía, revisamos) → `ramping` (auto parcial) → `active` (full). Cada salto es decisión explícita del AIDE.

---

## 5. Cambios de modelo de datos

- `ALTER TABLE tenants ADD COLUMN plan_tier text NOT NULL DEFAULT 'founding'` (valores: `founding`/`standard`/`trial`; CHECK).
- Posible `source_type` nuevo en `tenant_knowledge_submissions` para el origen Shopify (ej. `shopify_page`, `shopify_policy`) si el enum no lo cubre — verificar enum actual antes.
- Sin tablas nuevas: todo lo demás reusa lo existente.

---

## 6. Fases de construcción (build order, con verify)

> Cada fase se valida en la tienda real antes de pasar a la siguiente (dogfood).

**Fase 1 — Provisioning (pasos 1 y 2 "bien hechos"):**
1. Migración `plan_tier`. → verify: columna + CHECK aplicados en staging.
2. Provisioning service (service_role: invite + tenant + user + onboarding + assignment + clone starter). → verify: tests unit + crea el tenant de la tienda real.
3. Endpoint `POST /tenants` super_admin + guardas de rol. → verify: 403 a no-super_admin; 201 crea todo.
4. UI "Nuevo cliente" en dashboard. → verify: crea tenant + llega el magic link.
5. Lifecycle `initial→discovery` al enviar invite. → verify: estado en DB.

**Fase 2 — Portal de acceso del cliente:**
6. Wizard: paso de subida docs/URLs → `pending_review`. → verify: submission creada.
7. Shopify token paste + validación + guardado cifrado. → verify: `shop.json` 200, fila en `tenant_integrations`.
8. Chatwoot token paste + auto-creación de webhook vía API. → verify: webhook creado en Chatwoot, smoke inbound 200 con HMAC.
9. Botones OAuth Gorgias/Zendesk (reuso). → verify: callback persiste token (cuando las apps estén registradas).
10. Lifecycle `discovery→building` por checklist. → verify: transición automática al cumplir condiciones.

**Fase 3 — KB bootstrap Shopify + starter agente:**
11. Métodos Shopify `list_pages/blogs/articles` + reuso `get_policies`. → verify: trae contenido real de la tienda.
12. Detección de páginas relevantes + HTML→markdown → `pending_review`. → verify: submissions con markdown limpio.
13. Starter pack AOPs/playbook/facts e-commerce ES + clonado en provisioning. → verify: tenant nuevo nace con AOPs que `select_aop` clasifica.

**Fase 4 — Validación end-to-end en la tienda real:**
14. Smoke test e2e (webhook → agente → respuesta → traza LangSmith ↔ Supabase). → verify: cadena completa como conv `99386d3b`.
15. Simulator **25/25** contra el tenant real. → verify: 25/25 critical asserts, judge Sonnet ≥8/10, 0 L3 sin approval, <$5, 100% runs en LangSmith correlacionados.

---

## 7. Decisiones diferidas / huecos de producto conscientes

- **Tier trial / self-serve público**: diferido a Bloque 2+. La arquitectura por invitación ya lo soporta (exponer el mismo service tras un signup con guardarraíles). Hoy solo la columna `plan_tier`.
- **Shopify OAuth app (un clic)**: diferido. El token-paste cubre el primer tramo de clientes managed. Migrar a OAuth cuando el volumen self-serve lo justifique.
- **Email branded por Postmark**: el invite usa SMTP de Supabase ahora; migrar a plantilla Postmark cuando importe la marca/deliverability.
- **Lifecycle por métricas**: descartado hoy (0 clientes para calibrar). Gating manual del AIDE.

---

## 8. Prerequisitos para dogfood (inputs reales)

Para validar en la tienda nueva necesito:
1. Marca + `slug` del tenant.
2. Dominio `xxx.myshopify.com` + Admin API access token (custom app).
3. Confirmar trabajo contra **staging** (vía `railway run`, llave `INTEGRATIONS_SECRET_KEY` de staging).
4. Helpdesk: reusar Chatwoot `Purigu` o inbox propio de la tienda.
5. Email del `tenant_admin` para el invite.

---

## 9. Criterios de aceptación del onboarding productizado

- Un super_admin crea un cliente desde la UI y el `tenant_admin` entra por magic link **sin SQL manual**.
- El cliente conecta Shopify + helpdesk y sube KB **desde el portal**, sin que nosotros toquemos secretos por canales inseguros.
- Un tenant nuevo nace con starter AOPs/playbook/facts y lifecycle correcto.
- La tienda Shopify real queda onboarded end-to-end y pasa el simulator 25/25.
