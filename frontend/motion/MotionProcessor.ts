import type { LoadedMotion } from "./DatasetLoader";

export interface ProcessedMotion {
    id: string;
}

export class MotionProcessor {

    process(
        motion: LoadedMotion
    ): ProcessedMotion {

        return {
            id: motion.id,
        };

    }

}