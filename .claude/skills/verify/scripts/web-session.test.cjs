// Run: node --test .claude/skills/verify/scripts/web-session.test.cjs
const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawnSync } = require('child_process');
const { STAGING_REF, assertStaging, buildCookies, parseEnvFile, redact } = require('./session-lib.cjs');

const jwt = (ref) => `h.${Buffer.from(JSON.stringify({ ref, role: 'service_role' })).toString('base64url')}.s`;
const good = () => ({ SUPABASE_URL: `https://${STAGING_REF}.supabase.co`, SUPABASE_SERVICE_ROLE_KEY: jwt(STAGING_REF), SUPABASE_ANON_KEY: 'anon-key-value', APP_ENV: 'staging' });

test('acepta staging', () => assert.strictEqual(assertStaging(good()), STAGING_REF));

test('se niega con otro proyecto en la URL', () => {
  const env = { ...good(), SUPABASE_URL: 'https://otroproyectoxyz.supabase.co' };
  assert.throws(() => assertStaging(env), /no es el proyecto de staging/);
});

test('se niega con host que solo imita el de staging', () => {
  const env = { ...good(), SUPABASE_URL: `https://${STAGING_REF}.supabase.co.evil.com` };
  assert.throws(() => assertStaging(env), /no es el proyecto de staging/);
});

test('se niega con service role de otro proyecto', () => {
  const env = { ...good(), SUPABASE_SERVICE_ROLE_KEY: jwt('otroproyectoxyz') };
  assert.throws(() => assertStaging(env), /service role no es del proyecto de staging/);
});

test('se niega si APP_ENV es producción', () => {
  assert.throws(() => assertStaging({ ...good(), APP_ENV: 'production' }), /producción/);
});

test('los errores no contienen la key', () => {
  const env = { ...good(), SUPABASE_SERVICE_ROLE_KEY: jwt('otroproyectoxyz') };
  try { assertStaging(env); } catch (e) { assert.ok(!e.message.includes(env.SUPABASE_SERVICE_ROLE_KEY)); }
});

test('redact oculta las keys', () => {
  assert.strictEqual(redact('error con sekret-key-123 dentro', ['sekret-key-123']), 'error con [oculto] dentro');
});

test('cookie con el formato de @supabase/ssr, en chunks si es grande', () => {
  const small = buildCookies({ access_token: 'a', refresh_token: 'r' }, STAGING_REF, 'http://localhost:3000');
  assert.strictEqual(small.length, 1);
  assert.strictEqual(small[0].name, `sb-${STAGING_REF}-auth-token`);
  assert.deepStrictEqual(JSON.parse(Buffer.from(small[0].value.slice(7), 'base64url').toString()), { access_token: 'a', refresh_token: 'r' });
  const big = buildCookies({ access_token: 'x'.repeat(4000) }, STAGING_REF, 'http://localhost:3000');
  assert.deepStrictEqual(big.map((c) => c.name), [`sb-${STAGING_REF}-auth-token.0`, `sb-${STAGING_REF}-auth-token.1`]);
  assert.ok(big.every((c) => c.domain === 'localhost'));
});

test('parseEnvFile quita comillas y comentarios', () => {
  assert.deepStrictEqual(parseEnvFile('# c\nA="x"\nexport B=y\n'), { A: 'x', B: 'y' });
});

test('web-session.cjs contra un SUPABASE_URL ajeno sale 1 sin tocar la red ni imprimir la key', () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'ws-'));
  const secret = jwt('otroproyectoxyz');
  const script = path.join(repo, 'a/b/c/d/scripts');
  fs.mkdirSync(script, { recursive: true });
  for (const f of ['web-session.cjs', 'session-lib.cjs']) fs.copyFileSync(path.join(__dirname, f), path.join(script, f));
  fs.writeFileSync(path.join(script, '_pw.cjs'), `const path=require('path');module.exports={PROFILE:'/nonexistent',WEB:'http://localhost:3000',fs:require('fs'),path,openCtx(){throw new Error('no debería abrir navegador')},saveState(){}};`);
  fs.writeFileSync(path.join(repo, 'a/.env.staging'), `SUPABASE_URL=https://otroproyectoxyz.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=${secret}\nSUPABASE_ANON_KEY=anon-anon-anon\n`);
  const r = spawnSync(process.execPath, [path.join(script, 'web-session.cjs')], { encoding: 'utf8' });
  assert.strictEqual(r.status, 1);
  assert.match(r.stderr, /me niego/);
  assert.ok(!(r.stdout + r.stderr).includes(secret));
});
