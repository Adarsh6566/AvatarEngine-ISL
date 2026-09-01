import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RenderEngine } from '../core/RenderEngine';
import { VrmLoader } from '../avatar/loading/VrmLoader';
import { SkeletonRetargeter } from '../avatar/animation/SkeletonRetargeter';
import {
  loadSkeletonStream,
  toViewSpace,
  type SkeletonJointValue,
  type SkeletonStream,
  type SkeletonStreamFrame,
} from '../skeleton/SkeletonStream';
import { ActivityIndicator } from '../ui/ActivityIndicator';
import { PlaybackSpeedControl } from '../ui/PlaybackSpeedControl';
import { matchSigns, knownPhrases } from './SignLibrary';
import type { VRM } from '@pixiv/three-vrm';

/**
 * Composition root for the CAPTURED-MOTION signer.
 *
 * A separate application from the .vrma app at "/". This one performs signs
 * only by replaying skeleton motion captured from real ISL video and retargeted
 * onto the avatar — there is no AnimationMixer, no .vrma clip, no fingerspelling
 * and no backend. One avatar, one driver.
 */

const mount = document.querySelector<HTMLDivElement>('#app');
if (!mount) throw new Error('Mount element #app not found');
/** Non-nullable alias: frameCamera() reads this from inside a closure. */
const container: HTMLDivElement = mount;

// Desktop framing. Preserved exactly on wide viewports; frameCamera() below
// only pulls back on narrow portrait ones, where the caption and input bar
// cover a much larger fraction of the screen.
const DESKTOP_DISTANCE = 4.6;
const DESKTOP_TARGET_Y = 1.2;
/** Camera sits slightly above its look-at point, as it always has. */
const CAMERA_RISE = 0.15;

const engine = new RenderEngine({
  container,
  background: 0xf2efe9,
  camera: {
    fov: 30,
    position: [0, DESKTOP_TARGET_Y + CAMERA_RISE, DESKTOP_DISTANCE],
    target: [0, DESKTOP_TARGET_Y, 0],
  },
});

engine.add(new THREE.AmbientLight(0xffffff, 1.5));
const key = new THREE.DirectionalLight(0xffffff, 2.2);
key.position.set(1, 1.6, 1.4);
engine.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 0.7);
fill.position.set(-1.4, 0.6, 0.8);
engine.add(fill);

const controls = new OrbitControls(engine.camera, engine.domElement);
controls.target.set(0, DESKTOP_TARGET_Y, 0);
controls.enableDamping = true;
engine.onUpdate(() => controls.update());

// --- avatar ----------------------------------------------------------------
// Every finger joint is driven ('full') — handshape carries meaning in ISL, and
// dropping the intermediate/distal bones reads as stiff.
//
// The cost is noise. Those finger segments are only ~0.013-0.016 view units
// long while jittering ~0.002 per frame — a ~15% perturbation on a short
// vector, and the retargeter normalises it to get a direction, so the angular
// swing is large. The jitter is NOT concentrated in depth (measured X 35% /
// Y 40% / Z 25% on rIndex1->2), so damping one axis would not help; smoothing
// the rotation over time is the lever that works.
//
// Measured on how_are_you across 5 finger bones (400 frame transitions), by
// how many frames jump more than 10 degrees:
//     0.7  -> 38/400   0.85 -> 11/400   0.9 -> 5/400   0.93 -> 0/400
// 0.9 removes ~87% of the visible spikes. Going higher is smoother still but
// the fingers start trailing the wrist, since at 25fps the blend settles over
// roughly 1/(1-s) frames.
//
// Tune live without editing: /signer.html?smooth=0.93  (0 = off, <1)
const SMOOTHING = (() => {
  const raw = new URLSearchParams(window.location.search).get('smooth');
  const n = raw === null ? NaN : Number(raw);
  return Number.isFinite(n) && n >= 0 && n < 1 ? n : 0.9;
})();

const retargeter = new SkeletonRetargeter({ fingerMode: 'full', fingerSmoothing: SMOOTHING });
let vrm: VRM | null = null;

// --- playback --------------------------------------------------------------
/** The sign currently being performed, or null when idle. */
let playing: { stream: SkeletonStream; cursor: number } | null = null;
/** Resolves when the current sign reaches its final frame. */
let onSignDone: (() => void) | null = null;
/** Backstop for a render loop that stops running mid-sign. See playSign(). */
let signWatchdog: ReturnType<typeof setTimeout> | null = null;
/** Playback multiplier from the speed control (1x-5x). */
let playbackRate = 1;

const streams = new Map<string, SkeletonStream>();

async function stream(path: string): Promise<SkeletonStream> {
  const cached = streams.get(path);
  if (cached) return cached;
  // Streams are 300-400 KB and fetched on demand, so the first play of a sign
  // has a visible wait. Show the spinner for it, not for cache hits.
  activity.show();
  try {
    const loaded = toViewSpace(await loadSkeletonStream(path));
    streams.set(path, loaded);
    return loaded;
  } finally {
    activity.hide();
  }
}

/**
 * End the current sign: hold its last pose, drop playback state, resolve the
 * caller waiting on it.
 *
 * Both the render loop and the watchdog finish signs, and whichever gets there
 * first must leave the same state behind — in particular onSignDone must be
 * cleared before it is called, so a resolve that starts the next sign cannot
 * see the finished one still in flight.
 */
function finishSign(): void {
  const current = playing;
  playing = null;
  if (signWatchdog !== null) {
    clearTimeout(signWatchdog);
    signWatchdog = null;
  }
  if (current && vrm) {
    const frames = current.stream.frames;
    retargeter.applyPose(vrm, frames[frames.length - 1].joints);
  }
  const done = onSignDone;
  onSignDone = null;
  done?.();
}

/**
 * Joints midway between two frames, at t in [0,1].
 *
 * Clips are 25fps and the display runs at 60, so playing the nearest frame
 * holds each pose for two or three refreshes and then jumps. On slow movement
 * that is invisible; on the fast reaches that signing is full of — measured up
 * to 0.126 view units between adjacent frames — it reads as a lurch, and the
 * hand crosses a lot of ground in one step, which is when it clips the body.
 *
 * The captured samples are unchanged; this only fills the gaps between them, so
 * the avatar travels the same path with the same timing, continuously.
 */
type Joints = SkeletonStreamFrame['joints'];

function lerpJoints(a: Joints, b: Joints, t: number): Joints {
  const out: Record<string, SkeletonJointValue> = {};
  for (const name of Object.keys(a)) {
    const p = a[name];
    const q = b[name];
    // A joint missing from either frame is carried through unchanged rather
    // than interpolated toward nothing.
    out[name] = p && q ? [
      p[0] + (q[0] - p[0]) * t,
      p[1] + (q[1] - p[1]) * t,
      p[2] + (q[2] - p[2]) * t,
      p[3] + (q[3] - p[3]) * t,
    ] : p;
  }
  return out;
}

engine.onUpdate((delta) => {
  if (!vrm) return;
  if (playing) {
    const { stream: s } = playing;
    playing.cursor += delta * s.fps * playbackRate;
    if (playing.cursor >= s.frames.length - 1) {
      playing.cursor = s.frames.length - 1;
      finishSign();
    } else {
      const i = Math.floor(playing.cursor);
      const t = playing.cursor - i;
      const joints =
        t < 1e-4
          ? s.frames[i].joints
          : lerpJoints(s.frames[i].joints, s.frames[i + 1].joints, t);
      retargeter.applyPose(vrm, joints);
    }
  }
  vrm.update(delta);
});

function playSign(s: SkeletonStream): Promise<void> {
  return new Promise((resolve) => {
    // Drop smoothing history so this sign does not start dragged toward the
    // last pose of the previous one.
    retargeter.reset();
    playing = { stream: s, cursor: 0 };
    onSignDone = resolve;

    // The cursor only advances inside requestAnimationFrame, which browsers
    // stop servicing in a hidden tab. A sign started just before the window is
    // backgrounded therefore never reaches its last frame, and because run()
    // awaits this promise the input and button stay disabled for good — every
    // sign tried afterwards looks like it failed to load, with no error shown.
    //
    // setTimeout still fires when hidden (throttled, which is fine here), so it
    // backstops the loop. The margin is deliberately generous: this must never
    // pre-empt playback that is merely slow, only a loop that has stopped.
    if (signWatchdog !== null) clearTimeout(signWatchdog);
    const expectedMs = (s.frames.length / s.fps / Math.max(playbackRate, 0.1)) * 1000;
    signWatchdog = setTimeout(() => {
      if (playing?.stream === s) finishSign();
    }, expectedMs * 2 + 1500);
  });
}

// --- UI --------------------------------------------------------------------
const input = document.querySelector<HTMLInputElement>('#text')!;
const button = document.querySelector<HTMLButtonElement>('#sign')!;
const caption = document.querySelector<HTMLDivElement>('#caption')!;
const gloss = document.querySelector<HTMLDivElement>('#gloss')!;
const status = document.querySelector<HTMLDivElement>('#status')!;
/** The outer .caption element carries the visibility state; #caption is the
 *  word inside its box, two levels down. Declared here because frameCamera()
 *  measures it during module init. */
const captionRoot = caption.closest<HTMLDivElement>('.caption')!;

document.querySelector<HTMLSpanElement>('#known')!.textContent = knownPhrases().join(' · ');

// --- responsive framing ------------------------------------------------------
const bar = document.querySelector<HTMLDivElement>('.bar')!;

/** Avatar extent in world units: boots to crown, with the +0.2 scene lift. */
const AVATAR_FEET_Y = 0.15;
const AVATAR_HEAD_Y = 2.05;

/**
 * Height the caption occupies at its WORST case, as a fraction of the viewport.
 *
 * The caption is empty when idle and grows when a sign starts, so measuring it
 * live would move the camera mid-sign. Measure it once holding the longest
 * phrase the library knows, and reserve that.
 */
function captionReserve(viewportHeight: number): number {
  const word = document.querySelector<HTMLDivElement>('#caption')!;
  const previous = word.textContent;
  const longest = knownPhrases().reduce((a, b) => (b.length > a.length ? b : a), '');
  word.textContent = longest;
  const height = captionRoot.getBoundingClientRect().height;
  word.textContent = previous;
  return Math.min((height + 24) / viewportHeight, 0.42);
}

/**
 * Fit the avatar into the space the floating chrome leaves free.
 *
 * The caption and input bar are position:fixed OVER the canvas, so the usable
 * band is what remains between them. On a desktop viewport that chrome is a
 * small fraction of the height and the original framing already clears it; on a
 * tall phone it can take over a third, which is what pushed the feet behind the
 * input bar. Blending on ASPECT rather than a pixel breakpoint means this reacts
 * to any viewport — phone, tablet, split-screen, resized window.
 */
function frameCamera(): void {
  const height = Math.max(container.clientHeight, 1);
  const aspect = container.clientWidth / height;

  const bottomFraction = Math.min((bar.getBoundingClientRect().height + 26) / height, 0.42);
  const topFraction = captionReserve(height);
  const usable = Math.max(0.32, 1 - topFraction - bottomFraction);

  const span = AVATAR_HEAD_Y - AVATAR_FEET_Y;
  const middle = (AVATAR_HEAD_Y + AVATAR_FEET_Y) / 2;

  // Frustum tall enough that the avatar plus 8% breathing room fits the usable
  // band, then the distance producing that frustum at this FOV.
  const frustum = (span * 1.08) / usable;
  const fitDistance = frustum / 2 / Math.tan(THREE.MathUtils.degToRad(engine.camera.fov) / 2);
  // Centre the avatar in the usable band, not in the viewport.
  const fitTargetY = middle - (frustum * (bottomFraction - topFraction)) / 2;

  // 0 at 1.2 aspect and wider (untouched desktop), 1 at 0.6 and taller.
  const t = THREE.MathUtils.clamp((1.2 - aspect) / (1.2 - 0.6), 0, 1);
  const distance = THREE.MathUtils.lerp(DESKTOP_DISTANCE, Math.max(fitDistance, DESKTOP_DISTANCE), t);
  const targetY = THREE.MathUtils.lerp(DESKTOP_TARGET_Y, fitTargetY, t);

  engine.camera.position.set(0, targetY + CAMERA_RISE, distance);
  controls.target.set(0, targetY, 0);
  controls.update();
}

frameCamera();
try {
  new ResizeObserver(() => frameCamera()).observe(container);
} catch {
  window.addEventListener('resize', frameCamera);
}

console.info(`[signer] finger smoothing ${SMOOTHING} (override with ?smooth=…)`);

// Same components the .vrma app uses — generic DOM widgets with no coupling to
// that pipeline's logic, so both apps stay visually consistent.
const activity = new ActivityIndicator(document.body);

// Speeds come from config.yaml (animation.playback_speeds) via APP_CONFIG, so
// both pipelines cycle through the same 1x-5x steps.
new PlaybackSpeedControl(document.body, {
  onChange: (speed) => {
    playbackRate = speed;
  },
});

function setCaption(text: string, glossText: string): void {
  caption.textContent = text;
  gloss.textContent = glossText;
  captionRoot.dataset.state = text ? 'active' : '';
}

let busy = false;

async function run(): Promise<void> {
  if (busy) return;
  const matches = matchSigns(input.value);

  if (matches.length === 0) {
    status.textContent = input.value.trim()
      ? 'No captured sign for that — try one of the phrases above.'
      : '';
    return;
  }

  busy = true;
  button.disabled = true;
  input.disabled = true;
  status.textContent = '';

  try {
    for (const match of matches) {
      setCaption(match.text, match.entry.gloss);
      const s = await stream(match.entry.path);
      console.info(
        `[signer] ${match.entry.gloss}: ${s.frames.length} frames @ ${s.fps}fps`,
      );
      await playSign(s);
    }
  } catch (error) {
    console.error('[signer]', error);
    status.textContent = 'Could not load that sign.';
  } finally {
    setCaption('', '');
    busy = false;
    button.disabled = false;
    input.disabled = false;
    input.focus();
  }
}

button.addEventListener('click', () => void run());
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') void run();
});

// --- boot ------------------------------------------------------------------
button.disabled = true;
status.textContent = 'Loading avatar…';
activity.show();

new VrmLoader()
  .load('/models/AvatarSample_C.vrm')
  .then((loaded) => {
    vrm = loaded;
    loaded.scene.position.y = 0.2;
    engine.add(loaded.scene);
    // Measure rest in the T-pose, before anything poses the model. Nothing here
    // applies a resting pose, so the capture is clean.
    retargeter.captureRest(loaded);
    button.disabled = false;
    status.textContent = '';
    activity.hide();
    input.focus();
    console.info('[signer] avatar ready');
  })
  .catch((error: unknown) => {
    console.error('[signer]', error);
    status.textContent = 'Avatar failed to load.';
    activity.hide();
  });

engine.start();
