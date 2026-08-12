import type { MotionReference } from "../MotionCatalog";

/**
 * A resolved, ready-to-play motion — the output of every MotionLoader.
 *
 * Defined here, with the loader contract, rather than inside any single loader.
 * DatasetLoader re-exports it so its existing consumers (MotionProcessor) import
 * it unchanged.
 */
export interface LoadedMotion {
    /** Gloss token — carried through so MotionPlayer can name the gesture. */
    id: string;
    motionId: string;
    assetPath: string;
    duration: number;
}

/**
 * MotionLoader — the contract for turning a MotionReference into a LoadedMotion.
 *
 * One implementation per motion source. VRMALoader (hand-authored .vrma clips)
 * is the only one today; a loader for motion derived from live ISL video capture
 * would implement this same interface and slot in behind DatasetLoader, with no
 * change to the rest of the pipeline.
 */
export interface MotionLoader {
    load(motion: MotionReference): LoadedMotion;
}
