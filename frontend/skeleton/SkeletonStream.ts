/**
 * SkeletonStream — the canonical, renderer-agnostic motion stream.
 *
 * This is the project's interchange format (promoted from the offline
 * pipeline's source_skeleton.v1): a flat list of named joints with a
 * parent→child hierarchy, plus per-frame 3D positions. It carries NO rotations,
 * NO VRM mapping, NO estimator-specific layout. Any renderer — neon armature,
 * VRM avatar, still-frame painter — consumes the same data, so hot-swapping a
 * renderer cannot change what motion is seen.
 *
 * This module is deliberately three.js-free: it is the data boundary, and stays
 * plain JSON in / plain objects out.
 */

export type SkeletonVec = readonly [x: number, y: number, z: number];

/** Position in a frame's coordinate space, plus the source confidence (0..1).
 *  `null` means the joint was not detected in this frame. */
export type SkeletonJointValue =
  | readonly [x: number, y: number, z: number, confidence: number]
  | null;

export interface SkeletonJointSpec {
  readonly name: string;
  readonly parent: string | null;
}

export interface SkeletonStreamFrame {
  readonly index: number;
  readonly timestamp: number; // seconds from clip start
  readonly joints: Readonly<Record<string, SkeletonJointValue>>;
}

/** Provenance that survives normalization, so viewers can label their clips. */
export interface SkeletonStreamSource {
  readonly gloss?: string;
  readonly source_video?: string;
  readonly estimator?: string;
  readonly coordinate_space?: string;
}

export interface SkeletonStream {
  readonly schema: string;
  /** Human-readable description of the coordinate space the positions are in. */
  readonly space: string;
  readonly fps: number;
  readonly frameCount: number;
  readonly duration: number; // seconds
  readonly joints: readonly SkeletonJointSpec[];
  readonly frames: readonly SkeletonStreamFrame[];
  readonly source?: SkeletonStreamSource;
}

export interface SkeletonEdge {
  readonly from: string;
  readonly to: string;
}

/** The bones of a stream: every joint that has a parent. */
export function streamEdges(stream: SkeletonStream): SkeletonEdge[] {
  return stream.joints
    .filter((j): j is SkeletonJointSpec & { parent: string } => j.parent !== null)
    .map((j) => ({ from: j.parent, to: j.name }));
}

const SCHEMA_PREFIX = 'source_skeleton.v1';

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function fail(reason: string): never {
  throw new Error(`[SkeletonStream] ${reason}`);
}

/** Validate the raw source_skeleton.v1 JSON and map it to a SkeletonStream.
 *  Positions are passed through verbatim in their original coordinate space. */
export function parseSkeletonStream(raw: unknown): SkeletonStream {
  if (!isObject(raw) || !isObject(raw.meta) || !Array.isArray(raw.frames)) {
    fail('expected { meta, frames }');
  }
  const meta = raw.meta;
  if (typeof meta.schema !== 'string' || !meta.schema.startsWith(SCHEMA_PREFIX)) {
    fail(`meta.schema must start with "${SCHEMA_PREFIX}", got ${JSON.stringify(meta.schema)}`);
  }
  if (!Array.isArray(meta.joints)) fail('meta.joints must be an array of {name, parent}');
  if (typeof meta.fps !== 'number' || meta.fps <= 0) fail('meta.fps must be a positive number');

  const joints: SkeletonJointSpec[] = meta.joints.map((j) => {
    if (!isObject(j) || typeof j.name !== 'string') fail('each meta.joints entry needs a name');
    return { name: j.name, parent: typeof j.parent === 'string' ? j.parent : null };
  });

  const fps = meta.fps;
  const frames: SkeletonStreamFrame[] = raw.frames.map((f, i) => {
    if (!isObject(f) || !isObject(f.joints)) fail(`frames[${i}] needs a joints object`);
    return {
      index: typeof f.index === 'number' ? f.index : i,
      timestamp: typeof f.timestamp === 'number' ? f.timestamp : i / fps,
      joints: f.joints as Readonly<Record<string, SkeletonJointValue>>,
    };
  });

  return {
    schema: meta.schema,
    space: typeof meta.coordinate_space === 'string' ? meta.coordinate_space : 'unknown',
    fps,
    frameCount: frames.length,
    duration: typeof meta.duration === 'number' ? meta.duration : frames.length / fps,
    joints,
    frames,
    source: {
      gloss: typeof meta.gloss === 'string' ? meta.gloss : undefined,
      source_video: typeof meta.source_video === 'string' ? meta.source_video : undefined,
      estimator: typeof meta.estimator === 'string' ? meta.estimator : undefined,
      coordinate_space: typeof meta.coordinate_space === 'string' ? meta.coordinate_space : undefined,
    },
  };
}

const ROOT_JOINT = 'hips';
const UP_JOINT = 'head';
const UP_REF_FALLBACK = 'chest';

/**
 * Convert a stream to the canonical view space: Y-up, per-frame root-centered
 * at `hips`, and unit-scaled so the mean hip→head distance is 1. This is the
 * ONE place coordinates are normalized — every renderer downstream gets
 * axis-consistent data and never re-does this math.
 *
 * Y-down sources (MediaPipe image space) are flipped; Y-up sources (future
 * SMPL-X adapter output) pass through. Root centering per frame removes global
 * drift while preserving the articulated motion, which is what sign playback
 * needs. If `hips` is missing in a frame, that frame is centered on the origin.
 */
export function toViewSpace(stream: SkeletonStream): SkeletonStream {
  const flipY = (stream.space ?? '').includes('Y down');

  const lengths: number[] = [];
  for (const f of stream.frames) {
    const a = f.joints[ROOT_JOINT];
    const b = f.joints[UP_JOINT] ?? f.joints[UP_REF_FALLBACK];
    if (a && b) {
      lengths.push(Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]));
    }
  }
  const unit = lengths.length > 0 ? lengths.reduce((s, v) => s + v, 0) / lengths.length : 1;
  const scale = unit > 1e-6 ? 1 / unit : 1;

  const frames = stream.frames.map((f) => {
    const root = f.joints[ROOT_JOINT] ?? [0, 0, 0, 0];
    const rx = root[0];
    const ry = root[1];
    const rz = root[2];
    const joints: Record<string, SkeletonJointValue> = {};
    for (const [name, v] of Object.entries(f.joints)) {
      if (!v) {
        joints[name] = null;
        continue;
      }
      joints[name] = [
        (v[0] - rx) * scale,
        (flipY ? ry - v[1] : v[1] - ry) * scale,
        (v[2] - rz) * scale,
        v[3],
      ];
    }
    return { index: f.index, timestamp: f.timestamp, joints };
  });

  return {
    ...stream,
    schema: `${stream.schema} → view`,
    space: 'view (Y-up, root-centered at hips, unit = mean hip→head)',
    frames,
    source: { ...stream.source, coordinate_space: stream.space },
  };
}

/** Fetch, validate, and normalize a stream in one call (the loader most
 *  consumers want). `url` is browser-relative, e.g. "/skeleton/hello.json". */
export async function loadSkeletonStream(url: string): Promise<SkeletonStream> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`[SkeletonStream] failed to fetch ${url}: HTTP ${response.status}`);
  }
  return toViewSpace(parseSkeletonStream(await response.json()));
}
