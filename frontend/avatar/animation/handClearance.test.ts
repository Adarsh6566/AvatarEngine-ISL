import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as THREE from 'three';
import { VRMHumanBoneName as V } from '@pixiv/three-vrm';
import { SkeletonRetargeter } from './SkeletonRetargeter';
import { closestPairAxis, pushToClear } from './handClearance';

/**
 * The hand-clearance pass, against the shipped avatar and the shipped clips.
 *
 * Worth having because this bug survived two attempts. The first fix (armIK)
 * measured WRIST separation and reported success while the hands were still
 * 0.6cm apart; the second pushed along the wrist axis and cleared only 13 of 21
 * frames. Both looked right until something measured the thing that actually
 * matters, so that is what these assert: the distance between the two hands'
 * BONES, on every frame of every clip.
 *
 * Runs on Node's own test runner and type stripping — no framework, no bundler,
 * no fixtures. The rig comes out of the real .vrm and the poses out of the real
 * .json, so nothing here can pass against a stand-in that has drifted.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const MODEL = path.join(ROOT, 'public/models/AvatarSample_C.vrm');
const CLIPS = path.join(ROOT, 'public/skeleton');

// ---------------------------------------------------------------- rig loading

interface RestBone { parent: string | null; world: THREE.Vector3 }

/** Read the humanoid rest hierarchy straight out of the .vrm's JSON chunk. */
function readRest(file: string): Map<string, RestBone> {
  const buf = fs.readFileSync(file);
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const total = view.getUint32(8, true);
  let at = 12;
  let gltf: any = null;
  while (at < total) {
    const len = view.getUint32(at, true);
    const type = view.getUint32(at + 4, true);
    at += 8;
    if (type === 0x4e4f534a) gltf = JSON.parse(buf.subarray(at, at + len).toString('utf8'));
    at += len;
  }
  assert.ok(gltf, 'no JSON chunk in the .vrm');

  const nodes = gltf.nodes as any[];
  const ext = gltf.extensions ?? {};
  const human: Record<string, number> = ext.VRMC_vrm
    ? Object.fromEntries(Object.entries<any>(ext.VRMC_vrm.humanoid.humanBones).map(([k, v]) => [k, v.node]))
    : Object.fromEntries((ext.VRM.humanoid.humanBones as any[]).map((b) => [b.bone, b.node]));

  const local = (n: any): THREE.Matrix4 => {
    if (n.matrix) return new THREE.Matrix4().fromArray(n.matrix);
    return new THREE.Matrix4().compose(
      new THREE.Vector3().fromArray(n.translation ?? [0, 0, 0]),
      new THREE.Quaternion().fromArray(n.rotation ?? [0, 0, 0, 1]),
      new THREE.Vector3().fromArray(n.scale ?? [1, 1, 1]),
    );
  };
  const world = new Map<number, THREE.Matrix4>();
  const parent = new Map<number, number | null>();
  const walk = (i: number, m: THREE.Matrix4, p: number | null): void => {
    const w = m.clone().multiply(local(nodes[i]));
    world.set(i, w);
    parent.set(i, p);
    for (const c of nodes[i].children ?? []) walk(c, w, i);
  };
  const child = new Set<number>();
  for (const n of nodes) for (const c of n.children ?? []) child.add(c);
  for (let i = 0; i < nodes.length; i++) if (!child.has(i)) walk(i, new THREE.Matrix4(), null);

  const boneOf = new Map<number, string>(Object.entries(human).map(([b, i]) => [i, b]));
  const rest = new Map<string, RestBone>();
  for (const [bone, node] of Object.entries(human)) {
    let p = parent.get(node) ?? null;
    let pb: string | null = null;
    while (p !== null && p !== undefined) {
      const hit = boneOf.get(p);
      if (hit) { pb = hit; break; }
      p = parent.get(p) ?? null;
    }
    rest.set(bone, { parent: pb, world: new THREE.Vector3().setFromMatrixPosition(world.get(node)!) });
  }
  return rest;
}

/**
 * A stand-in for three-vrm's NORMALIZED rig: rest rotations identity, each
 * bone offset from its parent by the rest delta. That is what the normalized
 * rig IS, so the retargeter cannot tell the difference — and building it here
 * keeps the suite free of a GLTF loader and a DOM.
 */
function buildRig(rest: Map<string, RestBone>) {
  const nodes = new Map<string, THREE.Object3D>();
  for (const b of rest.keys()) nodes.set(b, new THREE.Object3D());
  const root = new THREE.Object3D();
  for (const [b, v] of rest) {
    const n = nodes.get(b)!;
    const pw = v.parent ? rest.get(v.parent)!.world : new THREE.Vector3();
    n.position.copy(v.world).sub(pw);
    (v.parent ? nodes.get(v.parent)! : root).add(n);
  }
  root.updateMatrixWorld(true);
  const vrm = {
    humanoid: {
      getNormalizedBoneNode: (b: string) => nodes.get(b) ?? null,
      setNormalizedPose: (pose: Record<string, { rotation: number[] }>) => {
        for (const [b, p] of Object.entries(pose)) {
          nodes.get(b)?.quaternion.fromArray(p.rotation);
        }
      },
      update: () => root.updateMatrixWorld(true),
    },
  } as any;
  const span = rest.get('head')!.world.distanceTo(rest.get('hips')!.world);
  return { vrm, nodes, span };
}

function loadClip(sign: string) {
  const d = JSON.parse(fs.readFileSync(path.join(CLIPS, `${sign}.json`), 'utf8'));
  return d.frames.map((f: any) => {
    const o: Record<string, [number, number, number]> = {};
    for (const [k, v] of Object.entries<any>(f.joints)) o[k] = [v[0], v[1], v[2]];
    return o;
  });
}

const SIGNS = fs.readdirSync(CLIPS).filter((f) => f.endsWith('.json')).map((f) => f.replace('.json', ''));
const FINGERS = ['Thumb', 'Index', 'Middle', 'Ring', 'Little'];
const SEGMENTS = ['Proximal', 'Intermediate', 'Distal'];
const handBones = (side: 'left' | 'right') =>
  [side + 'Hand', ...FINGERS.flatMap((f) => SEGMENTS.map((s) => side + f + s))];

/** Play one clip and report what the two hands did. A FRESH rig every time:
 *  captureRest must see a T-pose, and the last run left a pose on the bones. */
function play(sign: string, handClearance: number | 'auto', armIK = true) {
  const { vrm, nodes, span } = buildRig(readRest(MODEL));
  const L = handBones('left').filter((b) => nodes.has(b));
  const R = handBones('right').filter((b) => nodes.has(b));
  const at = (b: string) => nodes.get(b)!.getWorldPosition(new THREE.Vector3()).divideScalar(span);

  const rt = new SkeletonRetargeter({ fingerMode: 'full', fingerSmoothing: 0.9, armIK, handClearance });
  rt.captureRest(vrm);

  const closest: number[] = [];
  const wrists: THREE.Vector3[][] = [];
  const fingerLocal: THREE.Quaternion[][] = [];
  const handWorld: THREE.Quaternion[][] = [];
  for (const frame of loadClip(sign)) {
    rt.applyPose(vrm, frame);
    let min = Infinity;
    for (const a of L) {
      const pa = at(a);
      for (const b of R) min = Math.min(min, pa.distanceTo(at(b)));
    }
    closest.push(min);
    wrists.push([at(V.LeftHand), at(V.RightHand)]);
    handWorld.push([V.LeftHand, V.RightHand].map((b) => nodes.get(b)!.getWorldQuaternion(new THREE.Quaternion())));
    fingerLocal.push(
      [...L, ...R].filter((b) => b.endsWith('Proximal') || b.endsWith('Intermediate') || b.endsWith('Distal'))
        .map((b) => nodes.get(b)!.quaternion.clone()),
    );
  }
  return { closest, wrists, fingerLocal, handWorld, span };
}

/**
 * Bone centres closer than this are inside each other's flesh.
 *
 * One knuckle pitch — 1.8cm on this rig, measured between adjacent proximals —
 * so two finger bones at exactly this distance are touching, and anything less
 * is interpenetration.
 *
 * Deliberately NOT the 1.35x the clearance pass aims for. That is a comfortable
 * MARGIN; this is the point of failure, and the two are different numbers. The
 * pass is also capped, on purpose, so it cannot reshape a gesture to buy margin
 * — and WE is exactly the sign that needs the cap, since the hands are supposed
 * to meet. After the arms were smoothed it settles at 2.0cm on two frames:
 * short of the 2.47cm target, clear of the 1.8cm that would actually overlap,
 * and reaching the target would have cost 4.3cm of wrist displacement per hand.
 * Asserting the target here failed the build for a sign that looks correct.
 */
const OVERLAP = 0.034;

/**
 * The distance the pass actually aims for — 1.35 knuckle pitches.
 *
 * A sign whose hands come within this is one the pass will act on, which is a
 * different question from whether it interpenetrates. Using OVERLAP for both
 * put `alright` (closest 1.9cm) outside the "collided" set while the pass still
 * moved it, and the two lists stopped agreeing.
 */
const ENGAGES = 0.045;
const degrees = (a: THREE.Quaternion, b: THREE.Quaternion) =>
  (2 * Math.acos(Math.min(1, Math.abs(a.dot(b)))) * 180) / Math.PI;

// ---------------------------------------------------------------------- tests

test('no sign leaves the two hands inside each other', () => {
  const bad: string[] = [];
  for (const sign of SIGNS) {
    const on = play(sign, 'auto');
    const frames = on.closest.filter((d) => d < OVERLAP).length;
    if (frames > 0) bad.push(`${sign}: ${frames} frames, closest ${(on.closest.reduce((a, b) => Math.min(a, b)) * on.span * 100).toFixed(1)}cm`);
  }
  assert.deepEqual(bad, [], 'hands interpenetrate');
});

test('the clips that collided are the only ones that move', () => {
  // WE, THANK_YOU and ALRIGHT are the three that overlap; every other sign must
  // come out bit-identical, so a collision fix cannot quietly reshape the rest.
  const moved: string[] = [];
  const collided: string[] = [];
  for (const sign of SIGNS) {
    const off = play(sign, 0);
    const on = play(sign, 'auto');
    // ENGAGES, not OVERLAP: this asks which signs the pass TOUCHES.
    if (off.closest.some((d) => d < ENGAGES)) collided.push(sign);
    const shift = Math.max(...off.wrists.map((w, i) =>
      Math.max(w[0].distanceTo(on.wrists[i][0]), w[1].distanceTo(on.wrists[i][1]))));
    if (shift > 1e-12) moved.push(sign);
  }
  assert.deepEqual(collided.sort(), ['alright', 'thank_you', 'we']);
  assert.deepEqual(moved.sort(), collided.sort(), 'a sign with no collision was altered');
});

test('the handshape and the palm facing survive untouched', () => {
  // The whole design rests on this: a hand TRANSLATES with its wrist and never
  // turns, because its world orientation is the captured direction and the
  // forearm cancels out of the arithmetic. If that were false the pass would be
  // twisting handshapes — which are the sign — to buy clearance.
  for (const sign of ['we', 'thank_you', 'alright']) {
    const off = play(sign, 0);
    const on = play(sign, 'auto');
    for (let i = 0; i < off.closest.length; i++) {
      for (let k = 0; k < off.fingerLocal[i].length; k++) {
        assert.ok(degrees(off.fingerLocal[i][k], on.fingerLocal[i][k]) < 1e-3, `${sign} finger ${k} turned at frame ${i}`);
      }
      for (let k = 0; k < 2; k++) {
        assert.ok(degrees(off.handWorld[i][k], on.handWorld[i][k]) < 1e-3, `${sign} hand ${k} turned at frame ${i}`);
      }
    }
  }
});

test('separating the hands does not make them judder', () => {
  // The correction rides on top of motion that four commits went into
  // smoothing, so it has to not reintroduce the jitter. A tenth of a percent of
  // hip→head is half a millimetre on this avatar.
  for (const sign of SIGNS) {
    const off = play(sign, 0);
    const on = play(sign, 'auto');
    const worstStep = (r: THREE.Vector3[][], k: number) =>
      Math.max(...r.slice(1).map((w, i) => w[k].distanceTo(r[i][k])));
    for (const k of [0, 1]) {
      const grew = worstStep(on.wrists, k) - worstStep(off.wrists, k);
      assert.ok(grew < 0.003, `${sign} arm ${k} step grew by ${(grew * 100).toFixed(3)}% of hip→head`);
    }
  }
});

test('turning the pass off, or turning armIK off, restores the old motion', () => {
  const a = play('we', 0);
  const b = play('we', 'auto');
  assert.ok(a.wrists.some((w, i) => w[0].distanceTo(b.wrists[i][0]) > 1e-6), 'auto did nothing');
  const c = play('we', 'auto', false);
  const d = play('we', 0, false);
  for (let i = 0; i < c.wrists.length; i++) {
    // The wrist is only a target while armIK owns the elbow; without it there is
    // nothing for this pass to move, and it must not pretend otherwise.
    assert.ok(c.wrists[i][0].distanceTo(d.wrists[i][0]) < 1e-12, 'clearance ran without armIK');
  }
});

test('the push solver reaches the clearance on random point sets', () => {
  // Solving each pair independently and taking the largest root LOOKS right and
  // is not: a push some other pair demanded can drag a pair that was already
  // clear back under, when its separation runs against the axis. That escaped
  // every one of the seventeen clips and this caught it at 4.51cm of 5.
  const rnd = (s: number) => new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).multiplyScalar(s);
  const clearance = 0.05;
  for (let trial = 0; trial < 4000; trial++) {
    const L = Array.from({ length: 5 }, () => rnd(0.2));
    const R = Array.from({ length: 5 }, () => rnd(0.2));
    const u = rnd(1).normalize();
    const delta = pushToClear(L, R, u, clearance, 1e9);
    assert.ok(Number.isFinite(delta) && delta >= 0, `delta ${delta}`);
    let min = Infinity;
    for (const a of L) {
      const pa = a.clone().addScaledVector(u, delta / 2);
      for (const b of R) min = Math.min(min, pa.distanceTo(b.clone().addScaledVector(u, -delta / 2)));
    }
    assert.ok(min >= clearance - 1e-9, `left ${min.toFixed(5)} apart, wanted ${clearance}`);
  }
});

test('the push solver handles the degenerate cases', () => {
  const u = new THREE.Vector3(1, 0, 0);
  const P = (x: number, y = 0, z = 0) => new THREE.Vector3(x, y, z);
  assert.equal(pushToClear([P(1)], [P(-1)], u, 0.05, 0.09), 0, 'already clear should not move');
  assert.ok(Number.isFinite(pushToClear([P(0)], [P(0)], u, 0.05, 0.09)), 'coincident points went non-finite');
  assert.equal(pushToClear([P(0)], [P(0)], u, 10, 0.09), 0.09, 'cap not applied');
  assert.equal(pushToClear([], [P(0)], u, 0.05, 0.09), 0, 'empty set should not move');
  assert.equal(closestPairAxis([P(9)], [P(-9)], 0.05, new THREE.Vector3()), null, 'axis found where nothing is close');
  const axis = closestPairAxis([P(0.01)], [P(0)], 0.05, new THREE.Vector3());
  assert.ok(axis && Math.abs(axis.length() - 1) < 1e-9, 'axis not unit');
  assert.ok(axis!.x > 0, 'axis must point from the right hand toward the left');
});
