import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RenderEngine } from './core/RenderEngine';
import { AvatarController } from './avatar';
import { translate } from './api/translate';
import { SignControls } from './ui/SignControls';
import { SignCaption } from './ui/SignCaption';
import { PlaybackSpeedControl } from './ui/PlaybackSpeedControl';
import { ActivityIndicator } from './ui/ActivityIndicator';
import { Sequencer } from './sign/Sequencer';
import { MotionCatalog } from './motion/MotionCatalog';
import { MotionPlayer } from './motion/MotionPlayer';
import { MotionProcessor } from './motion/MotionProcessor';
import { DatasetLoader } from './motion/DatasetLoader';
import { APP_CONFIG } from './config/appConfig';
import { AVATAR, fitToChrome } from './avatar/framing/fitToChrome';

/**
 * Composition root. Its only job is to construct modules, wire them together,
 * and start the loop — no rendering, animation, or loading logic. It imports
 * AvatarController from the module's public barrel ('./avatar') and never sees
 * VrmLoader, AnimationController, or ExpressionController.
 */
const mount = document.querySelector<HTMLDivElement>('#app');
if (!mount) throw new Error('Mount element #app not found');
/** Non-nullable alias: frameCamera() reads this from inside a closure, where
 *  the narrowing from the throw above does not reach. */
const container: HTMLDivElement = mount;

// Matches the page's paper tone so the canvas does not read as a cut-out panel.
const engine = new RenderEngine({ container, background: 0xf2efe9 });

// Minimal lighting so the avatar is visible. (Moves into a SceneEnvironment
// module in a later phase — lighting is not the RenderEngine's job.)
const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
keyLight.position.set(1, 1.6, 1.4);
engine.add(keyLight);

const fillLight = new THREE.DirectionalLight(0xffffff, 0.7);
fillLight.position.set(-1.4, 0.6, 0.8);
engine.add(fillLight);

engine.add(new THREE.AmbientLight(0xffffff, 1.5));

// Debug controls so you can orbit and inspect the avatar during development.
const controls = new OrbitControls(engine.camera, engine.domElement);
controls.target.set(0, 1, 0);
controls.enableDamping = true;
engine.onUpdate(() => controls.update());

/*
 * Keep the avatar clear of the floating chrome.
 *
 * The caption and the input bar are position:fixed over a full-bleed canvas.
 * This page previously did nothing about that and used the default camera, so
 * on any window short enough the caption — up to 60px of type in a ~100px box —
 * simply covered the avatar's head. The signer page had solved this and this
 * one had not; both now go through the same helper.
 *
 * The framed band comes from AVATAR — waist to crown, shared with the other
 * two pipelines, which all load this model with the same +0.2 lift. This page
 * previously guessed at 0 and 1.9, which was both wrong and its own copy.
 */
/** Never closer than the framing this page has always used. */
const MIN_DISTANCE = 3.5;

function frameCamera(): void {
  const captionRoot = document.querySelector<HTMLElement>('.vrma-caption');
  const word = captionRoot?.querySelector<HTMLElement>('.vrma-caption__word') ?? null;
  const previous = word?.textContent ?? null;
  // Measure at a worst case rather than as-found, so the camera does not shift
  // the instant a sign starts. This page's captions are arbitrary words, so a
  // representative long one stands in for the vocabulary.
  if (word) word.textContent = 'GOOD AFTERNOON';
  try {
    fitToChrome({
      container,
      camera: engine.camera,
      controls,
      top: captionRoot,
      bottom: document.querySelector<HTMLElement>('.vrma-bar'),
      feetY: AVATAR.signingFloorY,
      headY: AVATAR.crownY,
      minDistance: MIN_DISTANCE,
      rise: 0.3,
    });
  } finally {
    if (word) word.textContent = previous;
  }
}

// --- Motion pipeline: gloss token -> registered clip -----------------------
const catalog = new MotionCatalog();
const loader = new DatasetLoader();
const processor = new MotionProcessor();

const avatar = new AvatarController(engine);
const player = new MotionPlayer(avatar);

const sequencer = new Sequencer(catalog, loader, processor, player);

// --- UI --------------------------------------------------------------------
const caption = new SignCaption(document.body);
const activity = new ActivityIndicator(document.body);

let pendingTranslate: AbortController | null = null;

const signBar = new SignControls(document.body, {
  onSign: async (text) => {
    // Abort any in-flight translation (user re-submitted quickly).
    pendingTranslate?.abort();
    const controller = new AbortController();
    pendingTranslate = controller;

    signBar.setEnabled(false);
    activity.show();

    try {
      const segments = await translate(text, { signal: controller.signal });

      // If this request was superseded, ignore its result.
      if (controller.signal.aborted) return;

      if (segments.length === 0) {
        return;
      }

      await sequencer.play(segments);
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      // TimeoutError is surfaced as DOMException with name TimeoutError
      if (error instanceof DOMException && error.name === 'TimeoutError') {
        console.warn('[avatar-engine] translate timeout', error);
        return;
      }
      console.error('[avatar-engine]', error);
    } finally {
      activity.hide();
      if (pendingTranslate === controller) pendingTranslate = null;
      signBar.setEnabled(true);
      signBar.focus();
    }
  },
});

// Both widgets have appended themselves by now, so .caption and .bar exist to
// be measured. Re-run on resize: the avatar occupies a fixed fraction of the
// frame while the chrome is a fixed number of pixels, so their overlap changes
// with every viewport height.
frameCamera();
try {
  new ResizeObserver(() => frameCamera()).observe(container);
} catch {
  window.addEventListener('resize', frameCamera);
}

// Playback speed (bottom-right button). Scales both mixer timeScale and
// sequencer hold timing so animation + caption stay in sync.
new PlaybackSpeedControl(document.body, {
  clearOf: '.vrma-bar',
  onChange: (speed) => {
    avatar.setPlaybackRate(speed);
    sequencer.setPlaybackRate(speed);
  },
});

// The caption follows playback rather than being driven from the input handler,
// so it stays correct no matter what triggers a sequence.
sequencer.setListener({
  onSegmentStart: (segment) => caption.showSegment(segment),
  onGesture: (_segment, index) => caption.highlight(index),
  onFinish: () => caption.clear(),
});

// --- Boot ------------------------------------------------------------------
signBar.setEnabled(false);
activity.show();

avatar
  .load(APP_CONFIG.avatar.modelPath)
  .then(() => {
    console.info('[avatar-engine] avatar ready');
    signBar.setEnabled(true);
    activity.hide();
    signBar.focus();
  })
  .catch((error: unknown) => {
    console.error('[avatar-engine]', error);
    activity.hide();
  });

engine.start();
