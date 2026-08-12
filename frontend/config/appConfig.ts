/**
 * Frontend config — injected from config.yaml via Vite define (__APP_CONFIG__).
 * Falls back to config.yaml defaults so tests / tsc (no Vite) still work.
 */
declare const __APP_CONFIG__: AppConfig | undefined;

export interface AppConfig {
  readonly timeoutMs: number;
  readonly validationMax: number;
  readonly animation: {
    readonly gestureFade: number;
    readonly minHold: number;
    readonly maxHold: number;
    readonly missingMotion: number;
    readonly wordGap: number;
    readonly fingerspellHold: number;
    readonly fingerspellFade: number;
  };
  readonly avatar: {
    readonly modelPath: string;
    readonly concurrency: number;
    readonly wordPriority: readonly string[];
  };
  readonly speeds: readonly number[];
  readonly defaultSpeed: number;
}

const FALLBACK: AppConfig = {
  timeoutMs: 8000,
  validationMax: 500,
  animation: {
    gestureFade: 0.6,
    minHold: 1.5,
    maxHold: 3,
    missingMotion: 1.5,
    wordGap: 0,
    fingerspellHold: 2,
    fingerspellFade: 0.25,
  },
  avatar: {
    modelPath: '/models/AvatarSample_C.vrm',
    concurrency: 6,
    wordPriority: ['HELLO', 'THANKYOU', 'PLEASE', 'SORRY', 'YES', 'NO', 'ME', 'YOU', 'BYE'],
  },
  speeds: [1, 2, 3, 4, 5],
  defaultSpeed: 1,
} as const;

// Vite replaces __APP_CONFIG__ at build/dev; fallback for tsc/build without Vite.
export const APP_CONFIG: AppConfig =
  typeof __APP_CONFIG__ !== 'undefined' && __APP_CONFIG__ !== null ? (__APP_CONFIG__ as AppConfig) : FALLBACK;
