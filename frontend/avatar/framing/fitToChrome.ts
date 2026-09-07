import * as THREE from 'three';

/**
 * Where the avatar's landmarks sit in world units.
 *
 * Read off AvatarSample_C.vrm's rig, plus the +0.2 lift every pipeline applies
 * when it adds the scene. All three pages use the same model and the same lift,
 * so these live here rather than being restated (and drifting) in each.
 */
export const AVATAR = {
  /** Top of the skull, ~0.28 above the head JOINT at 1.768. */
  crownY: 2.05,
  hipsY: 1.227,
  kneeY: 0.79,
  bootsY: 0.15,

  /**
   * The bottom of the frame.
   *
   * The legs carry no linguistic information — ISL is signed between roughly
   * the hips and above the head — so framing them wastes half the screen on
   * exactly the thing nobody needs to read, and forces the hands smaller. This
   * is also how broadcast interpreters are shot: a medium shot from the waist,
   * not full body.
   *
   * Set just BELOW the hips rather than at them. Signs do drop to hip level,
   * and a floor drawn exactly at 1.227 would clip the hands out of frame on
   * the ones that do.
   */
  signingFloorY: 1.05,
} as const;

export interface FitToChromeOptions {
  /** The element the canvas fills. Its box is the viewport being fitted. */
  container: HTMLElement;
  camera: THREE.PerspectiveCamera;
  /** Kept in step with the camera so orbiting starts from the new centre. */
  controls?: { target: THREE.Vector3; update: () => void };
  /** Chrome floating over the top of the canvas — the caption. */
  top?: HTMLElement | null;
  /** Chrome floating over the bottom — the input bar. */
  bottom?: HTMLElement | null;
  /** Avatar extent in world units, boots to crown. */
  feetY: number;
  headY: number;
  /** Never move closer than this, so the avatar cannot balloon on a wide window. */
  minDistance: number;
  /** Camera sits slightly above its look-at point. */
  rise?: number;
}

/**
 * Frame the avatar into the band the floating chrome leaves free.
 *
 * The caption and the input bar are position:fixed OVER a full-bleed canvas, so
 * the space actually available to the avatar is what remains between them.
 * Nothing in CSS can express that — the canvas does not know where the head is,
 * and the caption does not know where the canvas has drawn one — so the
 * reconciliation has to happen in the camera.
 *
 * This was previously inside signer/main.ts and blended in by aspect ratio,
 * applying on tall phones and not at all on wide desktops. That was the wrong
 * axis: the avatar sits at a fixed FRACTION of the frame, while the caption is a
 * fixed number of PIXELS, so their collision is governed by viewport HEIGHT
 * alone. A short, wide window — a laptop, a half-height browser — got no
 * reserve at all, and the caption printed itself across the avatar's face.
 *
 * Now it always applies, on both pipelines.
 */
export function fitToChrome(options: FitToChromeOptions): void {
  const { container, camera, controls, top, bottom, feetY, headY, minDistance } = options;
  const height = Math.max(container.clientHeight, 1);

  // A fraction each, capped so that pathological chrome cannot leave no room.
  const reserve = (el: HTMLElement | null | undefined, gap: number) =>
    el ? Math.min((el.getBoundingClientRect().height + gap) / height, 0.42) : 0;

  const topFraction = reserve(top, 24);
  const bottomFraction = reserve(bottom, 26);
  const usable = Math.max(0.32, 1 - topFraction - bottomFraction);

  const span = headY - feetY;
  const middle = (headY + feetY) / 2;

  // A frustum tall enough for the avatar plus 8% breathing room to fit the
  // usable band, then the distance that produces it at this field of view.
  const frustum = (span * 1.08) / usable;
  const distance = Math.max(
    frustum / 2 / Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2),
    minDistance,
  );
  // Centre the avatar in the usable band rather than in the viewport: the two
  // are only the same when the chrome is symmetrical, and it never is.
  const targetY = middle - (frustum * (bottomFraction - topFraction)) / 2;

  camera.position.set(0, targetY + (options.rise ?? 0), distance);
  camera.lookAt(0, targetY, 0);
  if (controls) {
    controls.target.set(0, targetY, 0);
    controls.update();
  }
}

/**
 * Measure the caption at its WORST case rather than as it currently is.
 *
 * It is empty while idle and grows when a sign starts, so measuring it live
 * would move the camera the instant a sign began — the avatar would flinch on
 * every word. Fill it with the longest phrase the vocabulary can produce,
 * measure that, and put back what was there.
 */
export function measureAtLongest(
  wordEl: HTMLElement,
  boxEl: HTMLElement,
  longest: string,
): number {
  const previous = wordEl.textContent;
  wordEl.textContent = longest;
  const height = boxEl.getBoundingClientRect().height;
  wordEl.textContent = previous;
  return height;
}
