import manifest from "../../data/motion_manifest.json";

export interface MotionReference {
    /**
     * The gloss token this motion performs (e.g. "HELLO").
     *
     * This is the id AnimationController registers clips under, so it must
     * travel the whole pipeline — MotionPlayer hands it straight to
     * playGesture(). `motionId` is a dataset label and is NOT interchangeable
     * with it.
     */
    id: string;
    motionId: string;
    assetPath: string;
    duration: number;
}

export class MotionCatalog {

    /**
     * Resolve a gloss token to its motion, or null if none is registered.
     *
     * Returns null rather than throwing: the translator now emits fingerspelled
     * tokens (LETTER_A, DIGIT_7) that have no clips yet, and one of those must
     * skip a single sign — not abort the rest of the sentence.
     */
    getMotion(gloss: string): MotionReference | null {

        const motion = manifest[gloss as keyof typeof manifest];

        if (!motion) {
            return null;
        }

        // Stamp the gloss token onto the reference so later stages carry the id
        // without having to look it up again.
        return { id: gloss, ...motion };
    }

}
