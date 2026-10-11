// Usage: node web-login.cjs    ONE-TIME, done by the human: opens a headed Chromium on the local dashboard,
// the user types email+password themselves, and once the page leaves /login the session stays in profile/.
// The agent never types credentials.
const { PROFILE, fs, path, WEB, openCtx, saveState } = require('./_pw.cjs');
(async () => {
  const ctx = await openCtx({ headless: false });
  const page = ctx.pages()[0] || await ctx.newPage();
  await page.goto(`${WEB}/login`);
  console.log('Inicia sesión en la ventana que se abrió (tienes 5 min)…');
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 300000 });
  await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
  const cookies = await ctx.cookies();
  const auth = cookies.filter((c) => /auth-token/.test(c.name));
  // Names and expiry only, never values.
  console.log('cookies de sesión:', auth.map((c) => `${c.name.replace(/(auth-token).*/, '$1*')} (${c.expires > 0 ? 'expira ' + new Date(c.expires * 1000).toISOString().slice(0, 16) : 'de sesión: se pierde al cerrar'})`).join(', ') || 'NINGUNA');
  if (!auth.length) { console.error('el login no dejó cookies de sesión: no guardo nada'); await ctx.close(); process.exit(1); }
  await saveState(ctx);
  fs.writeFileSync(path.join(PROFILE, '.logged-in'), new Date().toISOString());
  console.log('sesión guardada en', PROFILE);
  await ctx.close();
})().catch((e) => { console.error(e.message); process.exit(1); });
