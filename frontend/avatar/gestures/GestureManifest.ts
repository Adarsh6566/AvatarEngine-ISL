/**
 * GestureManifest — the single source of truth for which gestures exist and
 * where their VRMA assets live. Data only, no logic.
 *
 * To add a gesture:
 *   1. Drop the .vrma file into /public/animations
 *   2. Add ONE entry below
 * AvatarController loads and registers every entry automatically on avatar init,
 * so no other code changes are needed.
 */
export interface GestureManifestEntry {
  /** Gesture id that AnimationController plays (matches GestureCommand.id). */
  readonly id: string;
  /** Public URL of the .vrma asset (served from /public). */
  readonly url: string;
}

export type GestureManifest = ReadonlyArray<GestureManifestEntry>;

export const GESTURE_MANIFEST: GestureManifest = [
  { id: 'HELLO', url: '/animations/hello_sign.vrma' },
  { id: 'SORRY', url: '/animations/sorry_sign.vrma' },
  { id: 'PLEASE', url: '/animations/please_sign.vrma' },
  { id: 'THANKYOU', url: '/animations/Thankyou_sign.vrma' },
  { id: 'BYE', url: '/animations/bye_sign.vrma' },
  { id: 'ME', url: '/animations/Me_sign.vrma' },
  { id: 'YOU', url: '/animations/You_sign1.vrma' },
  { id: 'NO', url: '/animations/no_sign.vrma' },
  { id: 'YES', url: '/animations/yes_sign.vrma' },
];
