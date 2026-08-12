import * as THREE from 'three';
import type { RenderEngine } from '../core/RenderEngine';
import { streamEdges, type SkeletonStream } from './SkeletonStream';
import type { SkeletonRenderer } from './SkeletonRenderer';

/**
 * NeonLineRenderer — the reference SkeletonRenderer.
 *
 * Draws the armature as glowing lines along the stream's hierarchy edges, with
 * joint nodes on top. It needs ONLY the stream's positions — no rotations, no
 * VRM, no @pixiv/three-vrm, no retargeting — so it is the ground-truth debugger:
 * if the neon figure signs correctly, the capture is good; if not, no avatar
 * work can save it. This is deliberately a first-class renderer, not a hack.
 */

const CORE_COLOR = 0x55e6ff; // bright cyan edges
const HALO_COLOR = 0x00a8ff; // faint additive glow edges
const JOINT_COLOR = 0xffffff;
const EDGE_EXTEND = 0.06; // halo extends past each endpoint for a soft bloom

export class NeonLineRenderer implements SkeletonRenderer {
  readonly kind = 'neon';

  private readonly group = new THREE.Group();
  private readonly core: THREE.LineSegments;
  private readonly halo: THREE.LineSegments;
  private readonly joints: THREE.Points;

  // Preallocated, per-frame-refilled position buffers (DynamicDraw).
  private corePositions = new Float32Array(0);
  private haloPositions = new Float32Array(0);
  private jointPositions = new Float32Array(0);

  private edges: { from: string; to: string }[] = [];
  private stream: SkeletonStream | null = null;
  private engine: RenderEngine | null = null;

  constructor() {
    this.core = new THREE.LineSegments(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({
        color: CORE_COLOR,
        transparent: true,
        opacity: 0.9,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    this.halo = new THREE.LineSegments(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({
        color: HALO_COLOR,
        transparent: true,
        opacity: 0.14,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    this.joints = new THREE.Points(
      new THREE.BufferGeometry(),
      new THREE.PointsMaterial({
        color: JOINT_COLOR,
        size: 0.055,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.95,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );

    // Static orientation aids; bodies are re-buffered every frame so we disable
    // frustum culling rather than chase stale bounding spheres.
    for (const obj of [this.core, this.halo, this.joints]) {
      obj.frustumCulled = false;
    }

    const grid = new THREE.GridHelper(3.2, 16, 0x3355aa, 0x18243a);
    grid.material.transparent = true;
    grid.material.opacity = 0.35;

    this.group.add(grid);
    this.group.add(new THREE.AxesHelper(0.9));
    this.group.add(this.halo, this.core, this.joints);
  }

  setStream(stream: SkeletonStream): void {
    this.stream = stream;
    this.edges = streamEdges(stream);

    const edgeCount = this.edges.length;
    const jointCount = stream.joints.length;
    this.corePositions = new Float32Array(edgeCount * 2 * 3);
    this.haloPositions = new Float32Array(edgeCount * 2 * 3);
    this.jointPositions = new Float32Array(jointCount * 3);

    this.core.geometry.setAttribute(
      'position',
      new THREE.BufferAttribute(this.corePositions, 3).setUsage(THREE.DynamicDrawUsage),
    );
    this.halo.geometry.setAttribute(
      'position',
      new THREE.BufferAttribute(this.haloPositions, 3).setUsage(THREE.DynamicDrawUsage),
    );
    this.joints.geometry.setAttribute(
      'position',
      new THREE.BufferAttribute(this.jointPositions, 3).setUsage(THREE.DynamicDrawUsage),
    );

    this.setFrame(0);
  }

  setFrame(index: number): void {
    const s = this.stream;
    if (!s || s.frames.length === 0) return;
    const frame = s.frames[Math.min(Math.max(index, 0), s.frames.length - 1)];
    const J = frame.joints;

    // Joint nodes: one point per detected joint, missing joints dropped.
    const jp = this.jointPositions;
    let jc = 0;
    for (let i = 0; i < s.joints.length; i++) {
      const v = J[s.joints[i].name];
      if (!v) continue;
      const o = jc * 3;
      jp[o] = v[0];
      jp[o + 1] = v[1];
      jp[o + 2] = v[2];
      jc++;
    }
    this.joints.geometry.setDrawRange(0, jc);
    (this.joints.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;

    // Edges: one line per bone whose both endpoints are present this frame.
    const cp = this.corePositions;
    const hp = this.haloPositions;
    let ec = 0;
    for (const e of this.edges) {
      const a = J[e.from];
      const b = J[e.to];
      if (!a || !b) continue;
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const dz = b[2] - a[2];
      const o = ec * 6;
      hp[o] = a[0] - dx * EDGE_EXTEND;
      hp[o + 1] = a[1] - dy * EDGE_EXTEND;
      hp[o + 2] = a[2] - dz * EDGE_EXTEND;
      hp[o + 3] = b[0] + dx * EDGE_EXTEND;
      hp[o + 4] = b[1] + dy * EDGE_EXTEND;
      hp[o + 5] = b[2] + dz * EDGE_EXTEND;
      cp[o] = a[0];
      cp[o + 1] = a[1];
      cp[o + 2] = a[2];
      cp[o + 3] = b[0];
      cp[o + 4] = b[1];
      cp[o + 5] = b[2];
      ec++;
    }
    this.core.geometry.setDrawRange(0, ec * 2);
    this.halo.geometry.setDrawRange(0, ec * 2);
    (this.core.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
    (this.halo.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
  }

  attach(engine: RenderEngine): void {
    this.engine = engine;
    engine.add(this.group);
    this.setFrame(0); // redraw in case geometry changed while detached
  }

  detach(): void {
    this.engine?.remove(this.group);
  }

  dispose(): void {
    this.detach();
    for (const obj of [this.core, this.halo, this.joints]) {
      obj.geometry.dispose();
      const materials = Array.isArray(obj.material) ? obj.material : [obj.material];
      materials.forEach((m) => m.dispose());
    }
  }
}
