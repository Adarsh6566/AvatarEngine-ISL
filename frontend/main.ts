import './style.css';
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

/**
 * Composition root. Its only job is to construct modules, wire them together,
 * and start the loop — no rendering, animation, or loading logic. It imports
 * AvatarController from the module's public barrel ('./avatar') and never sees
 * VrmLoader, AnimationController, or ExpressionController.
 */
const container = document.querySelector<HTMLDivElement>('#app');
if (!container) throw new Error('Mount element #app not found');

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

// Playback speed (bottom-right button). Scales both mixer timeScale and
// sequencer hold timing so animation + caption stay in sync.
new PlaybackSpeedControl(document.body, {
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
    avatar.setExpression('happy');
  })
  .catch((error: unknown) => {
    console.error('[avatar-engine]', error);
    activity.hide();
  });

engine.start();
