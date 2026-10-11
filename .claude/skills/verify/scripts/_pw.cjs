// Shared bits for the Playwright drivers. Playwright is installed by mise, not in the repo.
const path = require('path');
const fs = require('fs');
const dir = process.env.PLAYWRIGHT_DIR ||
  path.join(process.env.HOME, '.local/share/mise/installs/npm-playwright/latest/node_modules/playwright');
const { chromium } = require(dir);
const VERIFY_DIR = path.resolve(__dirname, '..');
const PROFILE = path.join(VERIFY_DIR, 'profile');   // persistent login (cookies) — gitignored, never print it
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
const base = { executablePath: findChromium(), args: ['--no-sandbox'] };
module.exports = { chromium, PROFILE, EVID, WEB, fs, path, base };
