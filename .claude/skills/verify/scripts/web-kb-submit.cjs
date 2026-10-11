// Usage: VERIFY_PROFILE=tenant node web-kb-submit.cjs <tenantId> "<título>" "<contenido>"
// Sends a knowledge submission from the client view (tenant_admin). It lands as "En revisión" and touches
// nothing the agent reads until a super_admin approves it (web-kb-review.cjs).
const { EVID, WEB, fs, path, openCtx, saveState } = require('./_pw.cjs');
const [tenantId, title, content] = process.argv.slice(2);
if (!tenantId || !title || !content) { console.error('uso: web-kb-submit.cjs <tenantId> "<título>" "<contenido>"'); process.exit(2); }
(async () => {
  const ctx = await openCtx({ headless: true });
  const page = ctx.pages()[0] || await ctx.newPage();
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
  await page.goto(`${WEB}/clients/${tenantId}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  if (new URL(page.url()).pathname.startsWith('/login')) { console.error('sesión expirada: /login'); await ctx.close(); process.exit(3); }
  await page.locator('#kb-title').waitFor({ timeout: 30000 });
  await page.locator('#kb-title').fill(title);
  await page.locator('#kb-content').fill(content);
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  await page.getByText(title).first().waitFor({ timeout: 30000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  await page.screenshot({ path: path.join(EVID, `${stamp}-kb-submit.png`), fullPage: true });
  fs.writeFileSync(path.join(EVID, `${stamp}-kb-submit.txt`), await page.innerText('body'));
  console.log(`enviado "${title}"; captura en evidence/${stamp}-kb-submit.png`);
  await saveState(ctx);
  await ctx.close();
})().catch((e) => { console.error(e.message.split('\n')[0]); process.exit(1); });
