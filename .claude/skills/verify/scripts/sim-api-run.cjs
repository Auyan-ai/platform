// Usage: node sim-api-run.cjs <tenant_uuid> <scenario_uuid>
// Launches a simulator run through the local API (`POST /simulations/runs`), the same path the dashboard uses, with the
// super_admin token of the saved session (web-session.sh; never printed). Spends Anthropic credit (judge included).
// Prints the HTTP status and the run fields; pass the run id to sim-dump.sh.
const { openCtx } = require('./_pw.cjs');
const [tenant, scenario] = process.argv.slice(2);
const UUID = /^[0-9a-f-]{36}$/;
if (!UUID.test(tenant || '') || !UUID.test(scenario || '')) {
  console.error('uso: sim-api-run.cjs <tenant_uuid> <scenario_uuid>');
  process.exit(2);
}
(async () => {
  const c = await openCtx({ headless: true });
  const ck = (await c.cookies()).filter((x) => /auth-token/.test(x.name)).sort((a, b) => a.name.localeCompare(b.name));
  await c.close();
  if (!ck.length) { console.error('sin sesión: corre web-session.sh'); process.exit(3); }
  let raw = ck.map((x) => x.value).join('');
  if (raw.startsWith('base64-')) raw = Buffer.from(raw.slice(7), 'base64url').toString();
  const tok = JSON.parse(decodeURIComponent(raw)).access_token;
  const API = process.env.API_LOCAL || 'http://localhost:8000';
  const r = await fetch(API + '/simulations/runs', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + tok, 'X-Tenant-Id': tenant, 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_id: scenario }),
    signal: AbortSignal.timeout(90000),
  });
  const body = await r.json().catch(() => ({}));
  const keep = ['id', 'status', 'termination_reason', 'turns_count', 'cost_cents', 'started_at', 'completed_at'];
  console.log(`HTTP ${r.status}`);
  console.log(JSON.stringify(r.ok ? Object.fromEntries(keep.map((k) => [k, body[k]])) : body));
  process.exit(r.ok ? 0 : 1);
})().catch((e) => { console.error(e.message.split('\n')[0]); process.exit(1); });
