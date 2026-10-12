// Pure helpers for web-session.cjs (testable without network).
const STAGING_REF = 'johidurhcobdkpvlnowl';
const CHUNK = 3180; // @supabase/ssr MAX_CHUNK_SIZE

function parseEnvFile(text) {
  const env = {};
  for (const line of text.split('\n')) {
    const m = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!m) continue;
    let v = m[2].trim();
    if (/^(".*"|'.*')$/.test(v)) v = v.slice(1, -1);
    env[m[1]] = v;
  }
  return env;
}

function projectRef(url) {
  let host;
  try { host = new URL(url).hostname; } catch { return null; }
  const m = host.match(/^([a-z0-9]+)\.supabase\.co$/);
  return m ? m[1] : null;
}

function jwtRef(jwt) {
  try { return JSON.parse(Buffer.from(jwt.split('.')[1], 'base64url').toString()).ref || null; } catch { return null; }
}

// Throws unless every signal says STAGING. Messages never include the key.
function assertStaging(env) {
  const ref = projectRef(env.SUPABASE_URL || '');
  if (ref !== STAGING_REF) throw new Error(`me niego: SUPABASE_URL no es el proyecto de staging (${STAGING_REF})`);
  if (!env.SUPABASE_SERVICE_ROLE_KEY) throw new Error('falta SUPABASE_SERVICE_ROLE_KEY en .env.staging');
  if (!env.SUPABASE_ANON_KEY) throw new Error('falta SUPABASE_ANON_KEY en .env.staging');
  if (jwtRef(env.SUPABASE_SERVICE_ROLE_KEY) !== STAGING_REF) throw new Error('me niego: la service role no es del proyecto de staging');
  if (/^prod/i.test(env.APP_ENV || env.ENV || '')) throw new Error('me niego: APP_ENV es producción');
  return ref;
}

// Same cookie layout @supabase/ssr writes: `base64-` + base64url(session JSON), split in `.N` chunks past 3180 chars.
function buildCookies(session, ref, webUrl) {
  const name = `sb-${ref}-auth-token`;
  const value = 'base64-' + Buffer.from(JSON.stringify(session)).toString('base64url');
  const parts = [];
  for (let i = 0; i < value.length; i += CHUNK) parts.push(value.slice(i, i + CHUNK));
  const expires = Math.floor(Date.now() / 1000) + 400 * 24 * 3600;
  const base = { domain: new URL(webUrl).hostname, path: '/', expires, httpOnly: false, secure: false, sameSite: 'Lax' };
  return parts.length === 1
    ? [{ ...base, name, value: parts[0] }]
    : parts.map((v, i) => ({ ...base, name: `${name}.${i}`, value: v }));
}

function redact(text, secrets) {
  let out = String(text);
  for (const s of secrets) if (s && s.length > 8) out = out.split(s).join('[oculto]');
  return out;
}

module.exports = { STAGING_REF, parseEnvFile, projectRef, jwtRef, assertStaging, buildCookies, redact };
