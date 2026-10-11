// Usage: VERIFY_PROFILE=tenant node web-facts.cjs <tenantId> <campo> "<valor>"
//   campo = id del input en la pestaña "Datos factuales": business_hours, support_email, support_phone,
//   website_url, return_window_days, return_policy_url, shipping_info.
// Edits ONE fact from the client view (tenant_admin) and saves. This changes the tenant's facts in staging:
// note the previous value it prints and restore it with a second run.
const { EVID, WEB, fs, path, openCtx, saveState } = require('./_pw.cjs');
const [tenantId, field, value] = process.argv.slice(2);
if (!tenantId || !field || value === undefined) { console.error('uso: web-facts.cjs <tenantId> <campo> "<valor>"'); process.exit(2); }
(async () => {
  const ctx = await openCtx({ headless: true });
  const page = ctx.pages()[0] || await ctx.newPage();
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
  const shot = (n) => page.screenshot({ path: path.join(EVID, `${stamp}-facts-${field}-${n}.png`), fullPage: true });
  await page.goto(`${WEB}/clients/${tenantId}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  if (new URL(page.url()).pathname.startsWith('/login')) { console.error('sesión expirada: /login'); await ctx.close(); process.exit(3); }
  await page.getByRole('tab', { name: 'Datos factuales' }).click();
  const input = page.locator(`#${field}`);
  await input.waitFor({ timeout: 30000 });
  const before = await input.inputValue();
  await shot('1-before');
  await input.fill(value);
  await page.getByRole('button', { name: 'Guardar' }).click();
  await page.getByText('Guardado', { exact: true }).waitFor({ timeout: 30000 });
  await shot('2-saved');
  fs.writeFileSync(path.join(EVID, `${stamp}-facts-${field}.txt`), `campo: ${field}\nantes: ${before}\ndespués: ${value}\n`);
  console.log(`guardado ${field}: "${before}" → "${value}"`);
  await saveState(ctx);
  await ctx.close();
})().catch((e) => { console.error(e.message.split('\n')[0]); process.exit(1); });
