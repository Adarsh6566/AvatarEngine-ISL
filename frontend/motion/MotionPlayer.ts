import { AvatarController } from "../avatar";
import type { ProcessedMotion } from "./MotionProcessor";

export class MotionPlayer {
    private readonly avatar: AvatarController;

    constructor(avatar: AvatarController) {
        this.avatar = avatar;
    }

    play(motion: ProcessedMotion, fadeSeconds?: number): void {
        this.avatar.playGesture(
            {
                type: "sign",
                id: motion.id,
            },
            fadeSeconds,
        );
    }

    /** Real clip length in seconds, or null if the gesture has no clip. */
    getDuration(gestureId: string): number | null {
        return this.avatar.getGestureDuration(gestureId);
    }

    /** Ease back to rest once a sequence is done. */
    relax(): void {
        this.avatar.relax();
    }
}
