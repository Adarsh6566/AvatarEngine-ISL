/**
 * Public API of the avatar module.
 *
 * Consumers — the composition root and, later, the AI layer — import ONLY from
 * here, never from deep paths. If a symbol is not re-exported here, it is
 * private to the module (VrmLoader, AnimationController, ExpressionController,
 * and the adapters all stay internal by design).
 */
export { AvatarController } from './controller/AvatarController';
export { GESTURE_FADE_SECONDS } from './animation/AnimationController';
export type { GestureCommand } from './gestures/GestureCommand';
export type { PlaybackHandle } from './animation/AnimationController';
