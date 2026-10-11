// Usage: node web-reject-approval.cjs <tenantId> "<motivo>"
// Rejects the ONLY pending L3 approval of the tenant from the dashboard (super_admin session).
// Rejecting executes nothing in Shopify. This script never clicks "Aprobar": approving runs a real,
// irreversible action on the store, which needs Kenny's explicit OK and is not automated here.
// Guard: it refuses to act unless exactly one pending approval is on screen.
const { EVID, WEB, fs, path, openCtx, saveState } = require('./_pw.cjs');
const [tenantId, reason] = process.argv.slice(2);
if (!tenantId || !reason) { console.error('uso: web-reject-approval.cjs <tenantId> "<motivo>"'); process.exit(2); }
(async () => {
  const ctx = await openCtx({ headless: true });
  const page = ctx.pages()[0] || await ctx.newPage();
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
  const shot = (n) => page.screenshot({ path: path.join(EVID, `${stamp}-approval-reject-${n}.png`), fullPage: true });
  await page.goto(`${WEB}/tenants/${tenantId}/approvals`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  if (new URL(page.url()).pathname.startsWith('/login')) { console.error('sesión expirada: /login'); await ctx.close(); process.exit(3); }
  await page.getByRole('heading', { name: 'Aprobaciones' }).waitFor({ timeout: 30000 });
  const rejectBtns = page.getByRole('button', { name: 'Rechazar', exact: true });
  await rejectBtns.first().waitFor({ timeout: 30000 });
  const n = await rejectBtns.count();
  if (n !== 1) { console.error(`hay ${n} aprobaciones pendientes en pantalla; me niego a actuar (esperaba exactamente 1)`); await shot('refused'); await ctx.close(); process.exit(4); }
  await shot('1-pending');
  await rejectBtns.click();
  const dialog = page.getByRole('dialog', { name: 'Rechazar acción' });
  await dialog.waitFor({ timeout: 10000 });
  await dialog.getByPlaceholder('Motivo del rechazo…').fill(reason);
  await shot('2-dialog');
  await dialog.getByRole('button', { name: 'Rechazar', exact: true }).click();
  await dialog.waitFor({ state: 'hidden', timeout: 30000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await shot('3-after');
  fs.writeFileSync(path.join(EVID, `${stamp}-approval-reject.txt`), await page.innerText('body'));
  console.log('rechazada; capturas en evidence/' + stamp + '-approval-reject-*.png');
  await saveState(ctx);
  await ctx.close();
})().catch((e) => { console.error(e.message.split('\n')[0]); process.exit(1); });
