// A driver that lands on /login calls renewAndRerun(): mint a fresh session (web-session.cjs) and re-run the same
// command once. If it returns (false), the caller exits 3 as before: already retried, or the mint failed.
const { spawnSync } = require('child_process');
const path = require('path');
function renewAndRerun() {
  if (process.env.VERIFY_RENEWED) return false;
  console.error('sesión expirada: renuevo con web-session.cjs (sin contraseña, solo staging)…');
  const mint = spawnSync(process.execPath, [path.join(__dirname, 'web-session.cjs')], { stdio: 'inherit', env: process.env });
  if (mint.status !== 0) return false;
  const re = spawnSync(process.execPath, process.argv.slice(1), { stdio: 'inherit', env: { ...process.env, VERIFY_RENEWED: '1' } });
  process.exit(re.status ?? 1);
}
module.exports = { renewAndRerun };
