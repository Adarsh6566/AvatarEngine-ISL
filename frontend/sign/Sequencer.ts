import type { MotionCatalog } from "../motion/MotionCatalog";
import { DatasetLoader } from "../motion/DatasetLoader";
import { MotionPlayer } from "../motion/MotionPlayer";
import { MotionProcessor } from "../motion/MotionProcessor";
import type { SignSegment } from "./SignSegment";
import { GESTURE_FADE_SECONDS } from "../avatar";
import { APP_CONFIG } from "../config/appConfig";

// All timings below are config.yaml-driven via APP_CONFIG (animation.*).

/** Hold for missing clip — caption pace while no .vrma exists. */
const MISSING_MOTION_SECONDS = APP_CONFIG.animation.missingMotion;

/** Floor on hold — prevents fade overlap from cutting sign off. */
const MIN_HOLD_SECONDS = APP_CONFIG.animation.minHold;

/** Ceiling — .vrma are padded to ~10.4s; cap keeps playback snappy. */
const MAX_HOLD_SECONDS = APP_CONFIG.animation.maxHold;

/** Fixed hold per letter + tight fade for fingerspelling. */
const FINGERSPELL = {
    holdSeconds: APP_CONFIG.animation.fingerspellHold,
    fadeSeconds: APP_CONFIG.animation.fingerspellFade,
} as const;

/** Pause after each word sign. */
const WORD_GAP_SECONDS = APP_CONFIG.animation.wordGap;

/**
 * Observer for playback progress. The Sequencer drives the avatar; anything
 * that wants to *show* what is happening (captions, progress, logging)
 * subscribes here rather than being reached into.
 */
export interface SequencerListener {
    /** A new word has started. */
    onSegmentStart?(segment: SignSegment): void;
    /** Gesture `index` of the current word is now playing. */
    onGesture?(segment: SignSegment, index: number): void;
    /** The whole sequence finished (or had nothing to play). */
    onFinish?(): void;
}

export class Sequencer {
    private readonly catalog: MotionCatalog;
    private readonly loader: DatasetLoader;
    private readonly processor: MotionProcessor;
    private readonly player: MotionPlayer;
    private listener: SequencerListener = {};

    private playing = false;
    private playbackRate = 1;

    constructor(
        catalog: MotionCatalog,
        loader: DatasetLoader,
        processor: MotionProcessor,
        player: MotionPlayer,
    ) {
        this.catalog = catalog;
        this.loader = loader;
        this.processor = processor;
        this.player = player;
    }

    /** Subscribe to playback progress. Replaces any previous listener. */
    setListener(listener: SequencerListener): void {
        this.listener = listener;
    }

    /** True while a sequence is in flight. */
    get isPlaying(): boolean {
        return this.playing;
    }

    /** Scale hold timing (1 = normal, 5 = 5×). Divides all delays by rate. */
    setPlaybackRate(rate: number): void {
        this.playbackRate = Math.max(0.1, rate);
    }

    get playbackRateValue(): number {
        return this.playbackRate;
    }

    /**
     * Play a sequence of words, one gesture at a time.
     *
     * Each gesture is held for its own manifest duration rather than a fixed
     * interval, so short signs do not stall and long ones are not cut off.
     * Concurrent calls are ignored — a second sequence starting mid-playback
     * would interleave gestures and desynchronise the caption.
     */
    async play(segments: readonly SignSegment[]): Promise<void> {
        if (this.playing) {
            console.warn("[Sequencer] already playing — ignoring request");
            return;
        }

        this.playing = true;

        try {
            for (const segment of segments) {
                this.listener.onSegmentStart?.(segment);

                for (let index = 0; index < segment.gestures.length; index += 1) {
                    this.listener.onGesture?.(segment, index);
                    await this.playGesture(segment.gestures[index], segment.spelled);
                }
            }
        } finally {
            // Settle out of the final sign rather than holding it indefinitely.
            this.player.relax();
            this.playing = false;
            this.listener.onFinish?.();
        }
    }

    /**
     * Play one gesture and hold for the mode-appropriate beat.
     *
     * `spelled` picks the timing profile: fingerspelled letters get a short
     * fixed hold + tight fade (FINGERSPELL) so a word spells at a natural pace;
     * word signs hold for the clip's own real length. Nothing is hardcoded per
     * gesture — the pipeline's `spelled` flag drives it.
     */
    private async playGesture(gestureId: string, spelled: boolean): Promise<void> {
        const motion = this.catalog.getMotion(gestureId);
        const fadeSeconds = spelled ? FINGERSPELL.fadeSeconds : GESTURE_FADE_SECONDS;

        // No clip for this token (e.g. a letter whose .vrma is missing). Hold the
        // caption at the mode's pace, then carry on — one missing sign must not
        // abort the rest of the sentence.
        if (!motion) {
            console.warn(`[Sequencer] no motion for "${gestureId}" — holding caption only`);
            await this.delay((spelled ? FINGERSPELL.holdSeconds : MISSING_MOTION_SECONDS) / this.playbackRate);
            return;
        }

        const loaded = this.loader.load(motion);
        const processed = this.processor.process(loaded);
        this.player.play(processed, fadeSeconds);

        // Fingerspelling: fixed short hold. Word sign: hold for the clip's real
        // length minus one fade window (so the next sign blends in as this one
        // lands), but clamped to [MIN_HOLD_SECONDS, MAX_HOLD_SECONDS] — the
        // clips are padded to ~10.4s, so the raw length would otherwise stall
        // the avatar between words.
        const holdSeconds =
            (spelled
                ? FINGERSPELL.holdSeconds
                : Math.min(
                      Math.max(
                          (this.player.getDuration(gestureId) ?? motion.duration) - GESTURE_FADE_SECONDS,
                          MIN_HOLD_SECONDS,
                      ),
                      MAX_HOLD_SECONDS,
                  ) + WORD_GAP_SECONDS) / this.playbackRate;

        await this.delay(holdSeconds);
    }

    private delay(seconds: number): Promise<void> {
        return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
    }
}
