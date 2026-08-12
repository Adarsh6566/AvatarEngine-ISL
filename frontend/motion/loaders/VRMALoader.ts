import type { MotionReference } from "../MotionCatalog";
import type { LoadedMotion, MotionLoader } from "./MotionLoader";

/**
 * VRMALoader — loads motion from the hand-authored VRMA dataset (entries tagged
 * dataset: "manual", plus the legacy word entries that carry no tag).
 *
 * Resolving a reference here is a projection, not a file read: the .vrma clip
 * itself is loaded and registered by the avatar module at init (keyed by id), so
 * this stage carries the reference's fields through for the rest of the pipeline
 * rather than fetching bytes. This is the logic that previously lived inline in
 * DatasetLoader.
 */
export class VRMALoader implements MotionLoader {
    load(motion: MotionReference): LoadedMotion {
        return {
            id: motion.id,
            motionId: motion.motionId,
            assetPath: motion.assetPath,
            duration: motion.duration,
        };
    }
}
