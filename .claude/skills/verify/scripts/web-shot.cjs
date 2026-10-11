// Usage: node web-shot.cjs <path> <name> [selector-to-wait-for]
//   e.g. node web-shot.cjs /tenants/<tenantId>/conversations conversations 'a[href*="/conversations/"]'
// Headless, reuses the saved login. Writes evidence/<ts>-<name>.png and <ts>-<name>.txt (visible text).
// Exits 3 if the dashboard bounced to /login (session expired → human re-runs web-login.cjs).
const { EVID, WEB, fs, path, openCtx, saveState } = require('./_pw.cjs');
const [route, name, waitFor] = process.argv.slice(2);
if (!route || !name) { console.error('uso: web-shot.cjs <ruta> <nombre> [selector]'); process.exit(2); }
(async () => {
  const ctx = await openCtx({ headless: true });
  const page = ctx.pages()[0] || await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  // "Failed to load resource" carries no URL, so report failed responses by URL instead.
  // apps/web has no favicon, so /favicon.ico 404s on every page: known, not a finding.
  page.on('response', (r) => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) errors.push(`http ${r.status()}: ${r.url()}`); });
  page.on('console', (m) => m.type() === 'error' && !m.text().startsWith('Failed to load resource') && errors.push('console: ' + m.text()));
  await page.goto(WEB + route, { waitUntil: 'domcontentloaded', timeout: 60000 });
  if (waitFor) await page.waitForSelector(waitFor, { timeout: 30000 });
  else await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  if (new URL(page.url()).pathname.startsWith('/login')) { console.error('sesión expirada: /login'); await ctx.close(); process.exit(3); }
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
  const out = path.join(EVID, `${stamp}-${name}`);
  await page.screenshot({ path: out + '.png', fullPage: true });
  fs.writeFileSync(out + '.txt', `url: ${page.url()}\n\n` + (await page.innerText('body')) + (errors.length ? '\n\n--- errores de consola ---\n' + errors.join('\n') : ''));
  console.log(out + '.png');
  console.log(errors.length ? `${errors.length} errores de consola (ver .txt)` : 'sin errores de consola');
  await saveState(ctx);
  await ctx.close();
})().catch((e) => { console.error(e.message); process.exit(1); });
