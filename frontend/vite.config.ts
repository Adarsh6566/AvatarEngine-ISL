import { defineConfig } from 'vite';
import { readFileSync, existsSync } from 'node:fs';

function configPath(): string {
  if (existsSync('config.yaml')) return 'config.yaml';
  if (existsSync('../config.yaml')) return '../config.yaml';
  if (existsSync('infra/config.yaml')) return 'infra/config.yaml';
  if (existsSync('../infra/config.yaml')) return '../infra/config.yaml';
  return 'config.yaml';
}
function backendPortFromConfig(): number {
  try {
    const p = configPath();
    if (!existsSync(p)) return 8000;
    const text = readFileSync(p, 'utf8');
    const m = text.match(/backend:\s*\n[\s\S]*?port:\s*(\d+)/);
    return m ? parseInt(m[1], 10) : 8000;
  } catch { return 8000; }
}
function backendHostFromConfig(): string {
  try {
    const p = configPath();
    if (!existsSync(p)) return '127.0.0.1';
    const text = readFileSync(p, 'utf8');
    const m = text.match(/backend:\s*\n[\s\S]*?host:\s*"?([^"\n]+)"?/);
    return m ? m[1].trim() : '127.0.0.1';
  } catch { return '127.0.0.1'; }
}
const BACKEND_PORT = process.env.BACKEND_PORT ? parseInt(process.env.BACKEND_PORT, 10) : backendPortFromConfig();
const BACKEND_HOST = process.env.BACKEND_HOST ?? backendHostFromConfig();

function frontendConfigFromYaml() {
  try {
    const p = configPath();
    if (!existsSync(p)) return null;
    const t = readFileSync(p, 'utf8');
    const get = (re: RegExp, fb: string) => t.match(re)?.[1]?.trim() ?? fb;
    const getNum = (re: RegExp, fb: number) => {
      const m = t.match(re);
      return m ? parseFloat(m[1]) : fb;
    };
    return {
      timeoutMs: getNum(/frontend:\s*\n[\s\S]*?timeout_ms:\s*(\d+)/, 8000),
      validationMax: getNum(/frontend:\s*\n[\s\S]*?validation:\s*\n[\s\S]*?text_max_length:\s*(\d+)/, 500),
      animation: {
        gestureFade: getNum(/gesture_fade_seconds:\s*([\d.]+)/, 0.6),
        minHold: getNum(/min_hold_seconds:\s*([\d.]+)/, 1.5),
        maxHold: getNum(/max_hold_seconds:\s*([\d.]+)/, 3),
        missingMotion: getNum(/missing_motion_seconds:\s*([\d.]+)/, 1.5),
        wordGap: getNum(/word_gap_seconds:\s*([\d.]+)/, 0),
        fingerspellHold: getNum(/fingerspell:\s*\n[\s\S]*?hold_seconds:\s*([\d.]+)/, 2),
        fingerspellFade: getNum(/fingerspell:\s*\n[\s\S]*?fade_seconds:\s*([\d.]+)/, 0.25),
      },
      avatar: {
        modelPath: get(/model_path:\s*"?([^"\n]+)"?/, '/models/AvatarSample_C.vrm'),
        concurrency: getNum(/avatar:\s*\n[\s\S]*?concurrency:\s*(\d+)/, 6),
        wordPriority: (() => {
          const m = t.match(/word_priority:\s*\[([^\]]+)\]/);
          if (!m) return ['HELLO', 'THANKYOU', 'PLEASE', 'SORRY', 'YES', 'NO', 'ME', 'YOU', 'BYE'];
          return m[1].split(',').map((s: string) => s.trim().replace(/^["']|["']$/g, ''));
        })(),
      },
      speeds: (() => {
        const m = t.match(/playback_speeds:\s*\[([^\]]+)\]/);
        if (!m) return [1, 2, 3, 4, 5];
        return m[1].split(',').map((s: string) => parseFloat(s.trim())).filter((n: number) => !isNaN(n));
      })(),
      defaultSpeed: getNum(/default_speed:\s*(\d+)/, 1),
    };
  } catch { return null; }
}
const FRONTEND_CFG = frontendConfigFromYaml();

// Two-page app: index.html + skeleton-viewer.html (both in this frontend/ dir).
export default defineConfig({
  root: '.',
  publicDir: '../public',
  define: FRONTEND_CFG ? { __APP_CONFIG__: JSON.stringify(FRONTEND_CFG) } : {},
  server: {
    fs: { allow: ['..'] },
    proxy: {
      // Frontend uses /api/* in production/dev when VITE_API_URL is unset.
      // Rewrite /api/translate -> /translate so backend route stays at /translate.
      '/api': {
        target: `http://${BACKEND_HOST}:${BACKEND_PORT}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      input: {
        main: 'index.html',
        'skeleton-viewer': 'skeleton-viewer.html',
      },
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/three')) return 'three';
          if (id.includes('@pixiv/three-vrm')) return 'three-vrm';
        },
      },
    },
  },
});
