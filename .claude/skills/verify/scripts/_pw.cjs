// Shared bits for the Playwright drivers. Playwright is installed by mise, not in the repo.
const path = require('path');
const fs = require('fs');
const dir = process.env.PLAYWRIGHT_DIR ||
  path.join(process.env.HOME, '.local/share/mise/installs/npm-playwright/latest/node_modules/playwright');
const { chromium } = require(dir);
const VERIFY_DIR = path.resolve(__dirname, '..');
// Persistent logins (cookies) — gitignored, never print them. VERIFY_PROFILE picks whose session to use:
// unset = super_admin (profile/), `tenant` = a tenant_admin of marea-studio (profile-tenant/), etc.
const NAME = process.env.VERIFY_PROFILE;
const PROFILE = path.join(VERIFY_DIR, NAME ? `profile-${NAME}` : 'profile');
const EVID = path.join(VERIFY_DIR, 'evidence');
const WEB = process.env.WEB_LOCAL || 'http://localhost:3000';
fs.mkdirSync(EVID, { recursive: true });
// The installed Playwright may expect a newer browser build than the one on disk, and downloading one is not
// ours to do silently. Use the newest full Chromium already in the cache (PW_CHROMIUM overrides).
function findChromium() {
  if (process.env.PW_CHROMIUM) return process.env.PW_CHROMIUM;
  const root = path.join(process.env.HOME, '.cache/ms-playwright');
  const dirs = fs.existsSync(root) ? fs.readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort() : [];
  const last = dirs[dirs.length - 1];
  return last ? path.join(root, last, 'chrome-linux64/chrome') : undefined;
}
// --password-store=basic: cookies are encrypted with a fixed key instead of the desktop keyring. With the keyring,
// a headed login and a headless run could disagree on the key, and Chromium silently drops what it cannot decrypt.
const base = { executablePath: findChromium(), args: ['--no-sandbox', '--password-store=basic'] };
// Session cookies (no expiry) die when Chromium closes, so the login also writes state.json and every run restores it
// (and rewrites it on exit, so rotated tokens survive). state.json is as sensitive as the profile: gitignored, never print it.
const STATE = path.join(PROFILE, 'state.json');
async function openCtx({ headless }) {
  const ctx = await chromium.launchPersistentContext(PROFILE, { ...base, headless, viewport: { width: 1360, height: 880 } });
  if (fs.existsSync(STATE)) {
    try { await ctx.addCookies(JSON.parse(fs.readFileSync(STATE, 'utf8')).cookies || []); } catch (e) { console.error('state.json ilegible:', e.message); }
  }
  return ctx;
}
async function saveState(ctx) {
  const st = await ctx.storageState();
  if (st.cookies.some((c) => /auth-token/.test(c.name))) fs.writeFileSync(STATE, JSON.stringify(st), { mode: 0o600 });
}
module.exports = { chromium, PROFILE, EVID, WEB, fs, path, base, openCtx, saveState };
