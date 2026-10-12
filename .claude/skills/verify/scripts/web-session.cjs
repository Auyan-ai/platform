// Usage: [VERIFY_PROFILE=tenant] [VERIFY_EMAIL=...] node web-session.cjs
// Crea la sesión del dashboard de STAGING sin contraseña: admin generate_link (service role) -> canje del token_hash
// en /auth/v1/verify -> cookie de sesión escrita en el perfil. No pasa por /auth/callback (que cierra la sesión del
// super_admin a propósito), así que no toca ni debilita ninguna regla de la web ni del API. Solo staging.
// Nunca imprime token, enlace ni key.
const { PROFILE, WEB, fs, path, openCtx, saveState } = require('./_pw.cjs');
const { parseEnvFile, assertStaging, buildCookies, redact } = require('./session-lib.cjs');

const REPO = path.resolve(__dirname, '../../../..');
const IS_TENANT = process.env.VERIFY_PROFILE === 'tenant';
const EMAIL = process.env.VERIFY_EMAIL || (IS_TENANT ? 'kennyrmv@gmail.com' : 'kenny+admin@auyan.es');
const WANT_ROLE = IS_TENANT ? 'tenant_admin' : 'super_admin';

(async () => {
  const envFile = path.join(REPO, '.env.staging');
  if (!fs.existsSync(envFile)) throw new Error(`falta ${envFile}`);
  const env = parseEnvFile(fs.readFileSync(envFile, 'utf8'));
  const ref = assertStaging(env);
  const secrets = [env.SUPABASE_SERVICE_ROLE_KEY, env.SUPABASE_ANON_KEY];
  const base = env.SUPABASE_URL.replace(/\/$/, '');
  const call = async (p, key, body) => {
    const r = await fetch(base + p, { method: 'POST', headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const text = await r.text();
    if (!r.ok) throw new Error(`${p} -> ${r.status} ${redact(text, secrets).slice(0, 200)}`);
    return JSON.parse(text);
  };

  console.log(`staging ${ref}: sesión para ${EMAIL} (perfil ${path.basename(PROFILE)}, rol esperado ${WANT_ROLE})`);
  const link = await call('/auth/v1/admin/generate_link', env.SUPABASE_SERVICE_ROLE_KEY, { type: 'magiclink', email: EMAIL });
  if (!link.hashed_token) throw new Error('generate_link no devolvió hashed_token (¿existe el usuario en staging?)');
  const session = await call('/auth/v1/verify', env.SUPABASE_ANON_KEY, { type: 'magiclink', token_hash: link.hashed_token });
  if (!session.access_token || !session.refresh_token) throw new Error('verify no devolvió sesión');

  const api = process.env.API_LOCAL || 'http://localhost:8000';
  try {
    const me = await fetch(api + '/users/me', { headers: { Authorization: 'Bearer ' + session.access_token }, signal: AbortSignal.timeout(8000) });
    if (me.ok) {
      const u = await me.json();
      console.log(`rol según el API: ${u.role}`);
      if (u.role !== WANT_ROLE) throw new Error(`el usuario ${EMAIL} es ${u.role}, no ${WANT_ROLE}`);
    } else console.log(`aviso: /users/me dio ${me.status}`);
  } catch (e) {
    if (/ es .*, no /.test(e.message)) throw e;
    console.log('aviso: API local no responde, rol sin comprobar (up.sh all)');
  }

  fs.mkdirSync(PROFILE, { recursive: true });
  const ctx = await openCtx({ headless: true });
  await ctx.clearCookies();
  await ctx.addCookies(buildCookies(session, ref, WEB));
  await saveState(ctx);
  fs.writeFileSync(path.join(PROFILE, '.logged-in'), new Date().toISOString());
  await ctx.close();
  console.log(`sesión guardada en ${PROFILE} (el access token dura ${session.expires_in}s; el refresh token lo renueva solo)`);
})().catch((e) => { console.error('web-session:', e.message); process.exit(1); });
