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
import { knownPhrases } from './SignLibrary';
import { translateToSigns } from './glossTranslate';
import { SpeechInput, isSpeechSupported } from './SpeechInput';
import { AVATAR, fitToChrome } from '../avatar/framing/fitToChrome';
import { hideLegs } from '../avatar/framing/hideLegs';
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


/**
 * Fit the avatar into the space the floating chrome leaves free.
 *
 * The measuring and the arithmetic both live in avatar/framing/fitToChrome, so
 * this page and the .vrma page cannot drift apart on it — they had already
 * drifted once, this page reserving the caption band and that one not
 * reserving it at all.
 *
 * The caption is filled with the longest phrase the library knows for the
 * duration of the measurement. It is empty while idle and grows when a sign
 * starts, so measuring it as-found would move the camera the moment a sign
 * began and the avatar would flinch on every word.
 */
function frameCamera(): void {
  const word = document.querySelector<HTMLDivElement>('#caption')!;
  const previous = word.textContent;
  word.textContent = knownPhrases().reduce((a, b) => (b.length > a.length ? b : a), '');
  try {
    fitToChrome({
      container,
      camera: engine.camera,
      controls,
      top: captionRoot,
      bottom: bar,
      feetY: AVATAR.signingFloorY,
      headY: AVATAR.crownY,
      minDistance: DESKTOP_DISTANCE,
      rise: CAMERA_RISE,
    });
  } finally {
    word.textContent = previous;
  }
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
  clearOf: '.bar',
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

/**
 * Phrases waiting to be signed.
 *
 * Typing produces one phrase at a time and can wait for the avatar, but speech
 * does not: someone talking keeps producing phrases while the previous one is
 * still being signed. Dropping those (as returning early on `busy` would) loses
 * words mid-sentence, so they queue and are signed in the order they were said.
 */
const queue: string[] = [];

function enqueue(text: string): void {
  if (text.trim()) queue.push(text);
  void drain();
}

async function drain(): Promise<void> {
  if (busy) return;
  while (queue.length) {
    const next = queue.shift();
    if (next !== undefined) await run(next);
  }
}

async function run(text: string): Promise<void> {
  if (busy) return;

  // Translation is a network round trip, so say something first — otherwise the
  // gap between pressing Sign and the avatar moving reads as the button not
  // having worked.
  status.textContent = 'Translating…';
  const { matches, source } = await translateToSigns(text);
  status.textContent = '';

  if (matches.length === 0) {
    status.textContent = text.trim()
      ? 'No captured sign for that — try one of the phrases above.'
      : '';
    return;
  }

  busy = true;
  button.disabled = true;
  // The input stays usable while listening: disabling it would fight the
  // interim transcript being written into it.
  input.disabled = !speech?.listening;
  // Named honestly: 'matched' means the string lookup ran, not that anything
  // was translated. Silence here would present the fallback as a translation.
  status.textContent = source === 'llm' ? 'translated' : 'matched';

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
    if (!speech?.listening) input.focus();
  }
}

button.addEventListener('click', () => enqueue(input.value));
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') enqueue(input.value);
});

// --- speech ------------------------------------------------------------------
// Spoken words go through exactly the same path as typed ones: the transcript
// is matched against SignLibrary and queued. Nothing about the signing changes,
// so a phrase the keyboard can sign the microphone can sign too, and one the
// library does not know fails the same way either way.
const mic = document.querySelector<HTMLButtonElement>('#mic')!;

const speech = isSpeechSupported()
  ? new SpeechInput({
      // Interim text is shown so it is obvious the microphone is working, but
      // never signed — the recogniser revises it right up until it settles.
      onInterim: (text) => {
        input.value = text;
      },
      onFinal: (text) => {
        input.value = text;
        enqueue(text);
      },
      onStateChange: (listening) => {
        mic.dataset.listening = String(listening);
        if (listening) {
          status.textContent = 'Listening…';
          input.placeholder = 'Speak, or type a sign…';
        } else {
          if (status.textContent === 'Listening…') status.textContent = '';
          input.placeholder = 'Type a sign…';
        }
      },
      onError: (message) => {
        status.textContent = message;
      },
    })
  : null;

if (speech) {
  mic.addEventListener('click', () => speech.toggle());
} else {
  // Recognition is a browser capability, not something the page can polyfill.
  mic.disabled = true;
  mic.title = 'Speech recognition is not available in this browser';
}

// --- boot ------------------------------------------------------------------
button.disabled = true;
status.textContent = 'Loading avatar…';
activity.show();

new VrmLoader()
  .load('/models/isl-avatar.vrm')
  .then((loaded) => {
    vrm = loaded;
    loaded.scene.position.y = 0.2;
    hideLegs(loaded);
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
