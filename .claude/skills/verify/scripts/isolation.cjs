// Usage: VERIFY_PROFILE=tenant node isolation.cjs <ownConversationId> <foreignConversationId>
// Tenant isolation at the API: uses the tenant_admin's own token (read from the saved session, never printed) against the
// local API. Expects 200 on own data and 404 on another tenant's conversation, 403 on the super_admin routes.
// Exit 1 if any expectation fails.
const { openCtx } = require('./_pw.cjs');
const [own, foreign] = process.argv.slice(2);
if (!own || !foreign) { console.error('uso: isolation.cjs <conversación propia> <conversación de otro tenant>'); process.exit(2); }
(async () => {
  const c = await openCtx({ headless: true });
  const ck = (await c.cookies()).filter((x) => /auth-token/.test(x.name)).sort((a, b) => a.name.localeCompare(b.name));
  await c.close();
  if (!ck.length) { console.error('sin sesión: corre web-login.sh con este perfil'); process.exit(3); }
  let raw = ck.map((x) => x.value).join('');
  if (raw.startsWith('base64-')) raw = Buffer.from(raw.slice(7), 'base64url').toString();
  const tok = JSON.parse(decodeURIComponent(raw)).access_token;
  const API = process.env.API_LOCAL || 'http://localhost:8000';
  let bad = 0;
  const check = async (label, path, want) => {
    const r = await fetch(API + path, { headers: { Authorization: 'Bearer ' + tok } });
    const ok = want.includes(r.status);
    if (!ok) bad = 1;
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${r.status} (esperaba ${want.join('/')}) ${label}`);
  };
  await check('conversación propia', `/conversations/${own}`, [200]);
  await check('conversación de OTRO tenant', `/conversations/${foreign}`, [403, 404]);
  await check('/tenants/admin/list (solo super_admin)', '/tenants/admin/list', [403]);
  await check('/tenants/admin/review-queue (solo super_admin)', '/tenants/admin/review-queue', [403]);
  await check('/tenants/me', '/tenants/me', [200]);
  process.exit(bad);
})().catch((e) => { console.error(e.message.split('\n')[0]); process.exit(1); });
