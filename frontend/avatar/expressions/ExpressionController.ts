/**
 * Controls the avatar's facial expressions.
 *
 * Receives expression names (e.g. "happy", "blink") and forwards them
 * to an expression backend. This class is independent of three-vrm,
 * keeping the controller focused only on expression requests.
 */
/**
 * Interface for applying expressions to an avatar.
 *
 * The implementation decides how an expression name maps to the
 * underlying avatar (VRM presets or custom morph targets).
 *
 * TODO: Add expression intensity and smooth transitions.
 */
export interface ExpressionBackend {
  applyExpression(name: string): void;
}

export class ExpressionController {
  private backend: ExpressionBackend | null = null;

 // Sets an expression and forwards it to the backend if attached.
  attach(backend: ExpressionBackend): void {
    this.backend = backend;
  }

// Applies a named expression using the configured backend.
  setExpression(name: string): void {
    const expression = this.normalize(name);
    console.info(`[ExpressionController] setExpression "${expression}"`);
    this.backend?.applyExpression(expression);
    // support intensity (0..1) and blending several concurrent
    // expressions (e.g. an eyebrow-raise grammatical marker over a mouth shape).
  }

  private normalize(name: string): string {
    if (typeof name !== 'string' || name.trim().length === 0) {
      throw new Error('[ExpressionController] expression name must be a non-empty string');
    }
    // Only trim whitespace. Expression name resolution belongs to the backend.
    return name.trim();
  }
}
