// Usage: node web-kb-review.cjs <tenantId> "<título>" approve|reject
// Reviews ONE pending knowledge submission from the super_admin queue (/tenants/<id>/knowledge).
// approve indexes it into the tenant's KB (the agent starts using it): only with Kenny's OK, and retire it
// afterwards with a soft delete of its knowledge_base_documents row. reject indexes nothing.
// Guard: it refuses to act unless exactly one pending item carries that title.
const { EVID, WEB, fs, path, openCtx, saveState } = require('./_pw.cjs');
const [tenantId, title, action] = process.argv.slice(2);
if (!tenantId || !title || !['approve', 'reject'].includes(action)) { console.error('uso: web-kb-review.cjs <tenantId> "<título>" approve|reject'); process.exit(2); }
(async () => {
  const ctx = await openCtx({ headless: true });
  const page = ctx.pages()[0] || await ctx.newPage();
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
  const shot = (n) => page.screenshot({ path: path.join(EVID, `${stamp}-kb-review-${n}.png`), fullPage: true });
  await page.goto(`${WEB}/tenants/${tenantId}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  if (new URL(page.url()).pathname.startsWith('/login')) { console.error('sesión expirada: /login'); await ctx.close(); process.exit(3); }
  await page.getByRole('heading', { name: 'KB pending review' }).waitFor({ timeout: 30000 });
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
  const items = page.getByRole('button').filter({ hasText: title });
  const n = await items.count();
  if (n !== 1) { console.error(`hay ${n} pendientes con el título "${title}"; me niego a actuar (esperaba exactamente 1)`); await shot('refused'); await ctx.close(); process.exit(4); }
  await items.click();
  await shot('1-selected');
  const label = action === 'approve' ? 'Aprobar' : 'Rechazar';
  await page.getByRole('button', { name: label, exact: true }).click();
  await items.waitFor({ state: 'detached', timeout: 60000 });
  await shot('2-after');
  fs.writeFileSync(path.join(EVID, `${stamp}-kb-review.txt`), `acción: ${action}\ntítulo: ${title}\n\n` + (await page.innerText('body')));
  console.log(`${action} "${title}"; capturas en evidence/${stamp}-kb-review-*.png`);
  await saveState(ctx);
  await ctx.close();
})().catch((e) => { console.error(e.message.split('\n')[0]); process.exit(1); });
