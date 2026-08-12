import type { MotionReference } from "./MotionCatalog";
import type { LoadedMotion, MotionLoader } from "./loaders/MotionLoader";
import { VRMALoader } from "./loaders/VRMALoader";

// Re-exported so existing consumers (e.g. MotionProcessor) keep importing
// LoadedMotion from here — DatasetLoader's public surface is unchanged.
export type { LoadedMotion } from "./loaders/MotionLoader";

/**
 * DatasetLoader — coordinator over the MotionLoaders.
 *
 * It no longer loads anything itself: it inspects a MotionReference's source
 * dataset and delegates to the MotionLoader that owns that source. Today the
 * only source is the hand-authored VRMA dataset, so every reference routes to
 * VRMALoader; a future source — e.g. motion captured from live ISL video and
 * retargeted onto the avatar — adds one MotionLoader and one case in
 * selectLoader(), leaving callers and the Sequencer untouched.
 *
 * Public API is unchanged: load(MotionReference) -> LoadedMotion.
 */
export class DatasetLoader {

    private readonly vrma = new VRMALoader();

    load(motion: MotionReference): LoadedMotion {
        return this.selectLoader(motion).load(motion);
    }

    /**
     * Choose the loader for this reference's dataset, defaulting to VRMA.
     *
     * `dataset` is a manifest field that MotionCatalog's public MotionReference
     * type does not surface, so it is read structurally here rather than by
     * widening that type. Entries tagged "manual" and the untagged legacy word
     * entries both fall to the default today.
     */
    private selectLoader(motion: MotionReference): MotionLoader {
        const { dataset } = motion as { readonly dataset?: string };

        switch (dataset) {
            // case "video": return this.signAvatar;  // future: live ISL capture
            default:
                return this.vrma;
        }
    }

}
