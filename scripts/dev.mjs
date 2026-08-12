#!/usr/bin/env node
/**
 * dev.mjs — start the backend and frontend together from npm.
 *
 *   npm run dev:all
 *
 * npm equivalent of ./run.sh (minus auto-open): spawns uvicorn (:8000, --reload)
 * and Vite (:5173) as a single process group, so Ctrl+C — or either server
 * dying — stops both. No new dependencies.
 *
 * Python resolution: prefers the repo venv (.venv/bin/python), then any
 * python3 that can import uvicorn/fastapi (e.g. a global anaconda python).
 */
import { spawn, execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

function portFromConfig(key, fallback) {
  try {
    const text = readFileSync(join(ROOT, 'config.yaml'), 'utf8');
    const re = key === 'backend' ? /backend:\s*\n[\s\S]*?port:\s*(\d+)/ : /frontend:\s*\n[\s\S]*?dev_port:\s*(\d+)/;
    const m = text.match(re);
    return m ? parseInt(m[1], 10) : fallback;
  } catch { return fallback; }
}
function hostFromConfig(fallback) {
  try {
    const text = readFileSync(join(ROOT, 'config.yaml'), 'utf8');
    const m = text.match(/backend:\s*\n[\s\S]*?host:\s*"?([^"\n]+)"?/);
    return m ? m[1].trim() : fallback;
  } catch { return fallback; }
}
const BACKEND_PORT = process.env.BACKEND_PORT ? parseInt(process.env.BACKEND_PORT, 10) : portFromConfig('backend', 8000);
const BACKEND_HOST = process.env.BACKEND_HOST ?? hostFromConfig('127.0.0.1');
const FRONTEND_PORT = process.env.FRONTEND_PORT ? parseInt(process.env.FRONTEND_PORT, 10) : portFromConfig('frontend', 5173);
const isWin = process.platform === 'win32';

// --- python resolution -------------------------------------------------------
const venvCandidates = isWin
  ? [join(ROOT, '.venv', 'Scripts', 'python.exe'), join(ROOT, '.venv', 'Scripts', 'python3.exe')]
  : [join(ROOT, '.venv', 'bin', 'python'), join(ROOT, '.venv', 'bin', 'python3')];
const python = venvCandidates.find((p) => existsSync(p)) ?? 'python3';

if (!existsSync(join(ROOT, 'frontend', 'node_modules')) && !existsSync(join(ROOT, 'node_modules'))) {
  console.error('✗ node_modules missing — run `npm --prefix frontend install` first');
  process.exit(1);
}
try {
  execFileSync(python, ['-c', 'import uvicorn, fastapi'], { stdio: 'ignore' });
} catch {
  console.error(`✗ ${python} cannot import uvicorn/fastapi`);
  console.error(`  install with: ${python} -m pip install -r backend/requirements.txt`);
  process.exit(1);
}

// --- port preflight ----------------------------------------------------------
function portOpen(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const s = net.connect({ host, port, timeout: 800 });
    s.on('connect', () => { s.destroy(); resolve(true); });
    s.on('timeout', () => { s.destroy(); resolve(false); });
    s.on('error', () => resolve(false));
  });
}

for (const [label, port, host] of [['backend', BACKEND_PORT, BACKEND_HOST], ['frontend', FRONTEND_PORT, '127.0.0.1']]) {
  if (await portOpen(port, host)) {
    console.error(`✗ ${label} port ${port} is already in use`);
    console.error(`  free it with: lsof -ti:${port} | xargs kill`);
    process.exit(1);
  }
}

// --- spawn + group-kill ------------------------------------------------------
const children = [];
let shuttingDown = false;

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  // Kill the whole group so npm/vite and uvicorn's reloader children die too.
  for (const child of children) {
    if (child.exitCode !== null || child.killed) continue;
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      child.kill('SIGTERM');
    }
  }
  setTimeout(() => process.exit(0), 500);
}

function spawnServer(name, command, args, cwd) {
  const child = spawn(command, args, { cwd, stdio: 'inherit', detached: true });
  child.on('exit', (code, signal) => {
    if (!shuttingDown) {
      console.error(`\n✗ ${name} exited (${signal ?? code ?? 'unknown'})`);
      shutdown();
    }
  });
  children.push(child);
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

spawnServer('backend', python, ['-m', 'uvicorn', 'app:app', '--host', BACKEND_HOST, '--port', String(BACKEND_PORT), '--reload'], join(ROOT, 'backend'));
spawnServer('frontend', isWin ? 'npm.cmd' : 'npm', ['run', 'dev', '--', '--port', String(FRONTEND_PORT)], join(ROOT, 'frontend'));

console.log(`\n  backend  → http://${BACKEND_HOST}:${BACKEND_PORT}`);
console.log(`  frontend → http://localhost:${FRONTEND_PORT}`);
console.log(`  skeleton viewer → http://localhost:${FRONTEND_PORT}/skeleton-viewer.html`);
console.log('  Ctrl+C to stop both\n');
