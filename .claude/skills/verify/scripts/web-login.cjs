// Usage: node web-login.cjs    ONE-TIME, done by the human: opens a headed Chromium on the local dashboard,
// the user types email+password themselves, and once the page leaves /login the session stays in profile/.
// The agent never types credentials.
const { chromium, PROFILE, fs, path, WEB, base } = require('./_pw.cjs');
(async () => {
  const ctx = await chromium.launchPersistentContext(PROFILE, { ...base, headless: false, viewport: { width: 1360, height: 860 } });
  const page = ctx.pages()[0] || await ctx.newPage();
  await page.goto(`${WEB}/login`);
  console.log('Inicia sesión en la ventana que se abrió (tienes 5 min)…');
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 300000 });
  fs.writeFileSync(path.join(PROFILE, '.logged-in'), new Date().toISOString());
  console.log('sesión guardada en', PROFILE);
  await ctx.close();
})().catch((e) => { console.error(e.message); process.exit(1); });
