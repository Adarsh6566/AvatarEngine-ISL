import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RenderEngine } from '../core/RenderEngine';
import { loadSkeletonStream } from '../skeleton/SkeletonStream';
import { NeonLineRenderer } from '../skeleton/NeonLineRenderer';
import { SkeletonPlayer } from '../skeleton/SkeletonRenderer';

/**
 * Composition root for the standalone skeleton-stream viewer
 * (/skeleton-viewer.html) — a debug/QA harness.
 *
 * Loads one source_skeleton.v1 stream (default /skeleton/hello.json, override
 * with ?src=...) and plays it back as a neon armature. No VRM, no backend, no
 * motion pipeline: this proves the captured motion is good before any avatar
 * work, and doubles as the no-model debug mode. Wiring only, no logic.
 */

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing #${id}`);
  return node as T;
}

const container = document.querySelector<HTMLDivElement>('#app');
if (!container) throw new Error('Mount element #app not found');

const src = new URLSearchParams(window.location.search).get('src') ?? '/skeleton/hello.json';

const engine = new RenderEngine({
  container,
  background: 0x070b12,
  camera: { fov: 35, position: [0, 0.8, 2.6], target: [0, 0.5, 0] },
});

const controls = new OrbitControls(engine.camera, engine.domElement);
controls.target.set(0, 0.5, 0);
controls.enableDamping = true;
engine.onUpdate(() => controls.update());

const renderer = new NeonLineRenderer();
renderer.attach(engine);
const player = new SkeletonPlayer(renderer);

// --- HUD wiring ---------------------------------------------------------------
const hudClip = el<HTMLSpanElement>('hud-clip');
const hudStream = el<HTMLSpanElement>('hud-stream');
const hudMeta = el<HTMLSpanElement>('hud-meta');
const hudFrame = el<HTMLSpanElement>('hud-frame');
const btnPlay = el<HTMLButtonElement>('btn-play');
const btnRestart = el<HTMLButtonElement>('btn-restart');
const scrub = el<HTMLInputElement>('scrub');
const speed = el<HTMLSelectElement>('speed');
const loopBox = el<HTMLInputElement>('loop');

let speedMultiplier = 1;
speed.addEventListener('change', () => {
  speedMultiplier = Number(speed.value);
});

const syncPlayUi = () => {
  btnPlay.textContent = player.isPlaying ? 'Pause' : 'Play';
};

btnPlay.addEventListener('click', () => {
  player.toggle();
  syncPlayUi();
});
btnRestart.addEventListener('click', () => {
  player.seek(0);
  player.play();
  syncPlayUi();
});
scrub.addEventListener('input', () => {
  player.seek(Number(scrub.value));
});
loopBox.addEventListener('change', () => {
  player.loop = loopBox.checked;
});
window.addEventListener('keydown', (e) => {
  if (e.code === 'Space') {
    e.preventDefault();
    player.toggle();
    syncPlayUi();
  }
});

let lastIndex = -1;
engine.onUpdate((delta) => {
  player.step(delta * speedMultiplier);
  const i = player.currentIndex;
  if (i !== lastIndex) {
    lastIndex = i;
    hudFrame.textContent = `${i} / ${player.frameCount}`;
    scrub.value = String(i);
  }
});

// --- Load the stream ----------------------------------------------------------
async function boot(): Promise<void> {
  const stream = await loadSkeletonStream(src);
  player.setStream(stream);
  player.play();

  hudClip.textContent = stream.source?.gloss ?? '\u2014';
  hudStream.textContent = src;
  hudMeta.textContent =
    `${stream.fps} fps \u00b7 ${stream.frameCount} frames \u00b7 ${stream.space}`;
  scrub.max = String(stream.frameCount - 1);
  hudFrame.textContent = `0 / ${stream.frameCount}`;
  syncPlayUi();
}

boot().catch((error) => {
  console.error('[skeleton-viewer]', error);
  hudClip.textContent = 'load failed';
});
