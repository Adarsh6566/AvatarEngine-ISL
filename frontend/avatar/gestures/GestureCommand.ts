/**
 * Represents a gesture request from the AI.
 * Contains only the intent, not animation details.
 */

/**
 * Performs a named sign.
 * `id` identifies the gesture, not the animation.
 */
export interface SignGestureCommand {
  readonly type: 'sign';
  readonly id: string;
}

/**
 * All commands accepted by the avatar engine.
 * New command types can be added here as the engine evolves.
 // TODO: Add expression, gaze, and other command types in later phases.
 */
export type GestureCommand = SignGestureCommand;
