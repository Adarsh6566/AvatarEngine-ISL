#!/usr/bin/env node
// validate-vrm.mjs — is a candidate .vrm fit for ISL signing?
//
//   node scripts/validate-vrm.mjs <path-to.vrm> [more.vrm ...]
//
// Parses the VRM (a glTF .glb) directly — no three.js, no browser, no build.
// Reports: humanoid + hand + per-finger bones, facial expressions/blendshapes,
// and measured limb proportions (normalised to hip→head = 1, so you can compare
// a candidate against the signer data and against the current avatar).
//
// Priority for ISL:  hands > proportions > face > realism.
// A beautiful avatar with poor fingers is useless here — so hands gate the verdict.

import { readFileSync } from 'node:fs';
import { basename } from 'node:path';

// ---------- glb → glTF JSON ----------
function readGLTF(path) {
  const buf = readFileSync(path);
  if (buf.readUInt32LE(0) !== 0x46546c67) throw new Error('not a glb/vrm (bad magic)');
  // chunk 0 is JSON
  const jsonLen = buf.readUInt32LE(12);
  const json = JSON.parse(buf.toString('utf8', 20, 20 + jsonLen));
  return json;
}

// ---------- minimal column-major mat4 ----------
const IDENT = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1];
function compose(t = [0,0,0], r = [0,0,0,1], s = [1,1,1]) {
  const [x,y,z,w] = r, [sx,sy,sz] = s;
  const x2=x+x,y2=y+y,z2=z+z, xx=x*x2,xy=x*y2,xz=x*z2, yy=y*y2,yz=y*z2,zz=z*z2, wx=w*x2,wy=w*y2,wz=w*z2;
  return [
    (1-(yy+zz))*sx, (xy+wz)*sx, (xz-wy)*sx, 0,
    (xy-wz)*sy, (1-(xx+zz))*sy, (yz+wx)*sy, 0,
    (xz+wy)*sz, (yz-wx)*sz, (1-(xx+yy))*sz, 0,
    t[0], t[1], t[2], 1,
  ];
}
function mul(a, b) {
  const o = new Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++)
    o[c*4+r] = a[r]*b[c*4] + a[4+r]*b[c*4+1] + a[8+r]*b[c*4+2] + a[12+r]*b[c*4+3];
  return o;
}
const posOf = (m) => [m[12], m[13], m[14]];
const dist = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1], a[2]-b[2]);

// world transform of every node (rest pose)
function worldPositions(nodes) {
  const parent = new Array(nodes.length).fill(-1);
  nodes.forEach((n, i) => (n.children || []).forEach((c) => (parent[c] = i)));
  const world = new Array(nodes.length);
  const local = nodes.map((n) => (n.matrix ? n.matrix.slice() : compose(n.translation, n.rotation, n.scale)));
  const visit = (i) => {
    if (world[i]) return world[i];
    world[i] = parent[i] === -1 ? mul(IDENT, local[i]) : mul(visit(parent[i]), local[i]);
    return world[i];
  };
  return nodes.map((_, i) => posOf(visit(i)));
}

// ---------- VRM humanoid bone map (0.x and 1.0) ----------
function humanBones(gltf) {
  const v1 = gltf.extensions?.VRMC_vrm;
  const v0 = gltf.extensions?.VRM;
  const map = {};
  if (v1?.humanoid?.humanBones) {
    for (const [name, b] of Object.entries(v1.humanoid.humanBones)) map[name] = b.node;
    return { map, version: '1.0' };
  }
  if (v0?.humanoid?.humanBones) {
    for (const b of v0.humanoid.humanBones) map[b.bone] = b.node;
    return { map, version: '0.x' };
  }
  return { map, version: null };
}

const cap = (s) => s[0].toUpperCase() + s.slice(1);
const ok = (b) => (b ? '✓' : '✗');

function fingerSegments(version) {
  // VRM 1.0 thumb: Metacarpal/Proximal/Distal ; 0.x thumb: Proximal/Intermediate/Distal
  const thumb = version === '1.0' ? ['Metacarpal','Proximal','Distal'] : ['Proximal','Intermediate','Distal'];
  const other = ['Proximal','Intermediate','Distal'];
  return { Thumb: thumb, Index: other, Middle: other, Ring: other, Little: other };
}

// ---------- expressions / blendshapes ----------
function expressions(gltf) {
  const v1 = gltf.extensions?.VRMC_vrm?.expressions;
  const v0 = gltf.extensions?.VRM?.blendShapeMaster?.blendShapeGroups;
  let names = [];
  if (v1) names = [...Object.keys(v1.preset || {}), ...Object.keys(v1.custom || {})];
  else if (v0) names = v0.map((g) => g.name || g.presetName).filter(Boolean);
  // raw morph-target names on meshes (where ARKit shapes usually live)
  const morphs = new Set();
  for (const m of gltf.meshes || []) {
    for (const nm of m.extras?.targetNames || []) morphs.add(nm);
    for (const p of m.primitives || []) for (const nm of p.extras?.targetNames || []) morphs.add(nm);
  }
  return { names, morphs: [...morphs] };
}
const ARKIT = ['browInnerUp','browDownLeft','browOuterUpLeft','mouthPucker','mouthSmileLeft','jawOpen','eyeBlinkLeft'];
const VISEMES = ['aa','ih','ou','ee','oh','a','i','u','e','o'];
const hasAny = (list, keys) => {
  const low = list.map((x) => x.toLowerCase());
  return keys.some((k) => low.some((n) => n.includes(k.toLowerCase())));
};

// ---------- report one model ----------
function validate(path) {
  const gltf = readGLTF(path);
  const { map, version } = humanBones(gltf);
  const pos = worldPositions(gltf.nodes || []);
  const has = (bone) => map[bone] !== undefined;
  const L = [];
  const p = (s) => L.push(s);

  p(`\nAvatar: ${basename(path)}`);
  p(`VRM version:          ${version || 'NOT A VRM'}`);
  if (!version) { p('  → no VRM humanoid extension found; unusable.\n'); return { L, suitable: false }; }

  p(`Humanoid:             ${ok(has('hips') && has('head'))}`);
  p(`Left hand:            ${ok(has('leftHand'))}`);
  p(`Right hand:           ${ok(has('rightHand'))}`);

  const segs = fingerSegments(version);
  let handsComplete = true;
  for (const side of ['left', 'right']) {
    p(`\n${cap(side)} fingers:`);
    for (const finger of Object.keys(segs)) {
      const present = segs[finger].map((seg) => has(`${side}${finger}${seg}`));
      const all = present.every(Boolean);
      if (!all) handsComplete = false;
      const missing = all ? '' : '  (missing: ' + segs[finger].filter((_, i) => !present[i]).join(', ') + ')';
      p(`  ${finger.padEnd(7)} ${ok(all)}${missing}`);
    }
  }

  const { names, morphs } = expressions(gltf);
  const brow = hasAny(names, ['brow','surprised']) || hasAny(morphs, ['brow']);
  const mouth = hasAny(names, VISEMES) || hasAny(morphs, ['mouth','jawOpen']);
  const arkit = morphs.filter((m) => ARKIT.some((a) => m.toLowerCase() === a.toLowerCase())).length
             || names.filter((n) => ARKIT.some((a) => n.toLowerCase() === a.toLowerCase())).length;
  p(`\nFacial expressions:   ${ok(names.length || morphs.length)}  (${names.length} expressions, ${morphs.length} morph targets)`);
  p(`  Brow control:       ${ok(brow)}`);
  p(`  Mouth control:      ${ok(mouth)}`);
  p(`  ARKit-style shapes: ${arkit ? '✓ (' + arkit + ' matched)' : '✗  (face capture won’t map 1:1)'}`);

  // proportions — normalised to hip→head = 1
  const seg = (a, b) => (has(a) && has(b) ? dist(pos[map[a]], pos[map[b]]) : null);
  const hipHead = seg('hips', 'head');
  const n = (v) => (v != null && hipHead ? (v / hipHead).toFixed(3) : '—');
  const side = has('rightUpperArm') ? 'right' : 'left';
  const upper = seg(`${side}UpperArm`, `${side}LowerArm`);
  const fore  = seg(`${side}LowerArm`, `${side}Hand`);
  const hand  = seg(`${side}Hand`, `${side}MiddleDistal`) ?? seg(`${side}Hand`, `${side}MiddleProximal`);
  const shoulders = seg('leftUpperArm', 'rightUpperArm');
  p(`\nProportions (÷ hip→head, so hip→head = 1.000):`);
  p(`  Upper arm:          ${n(upper)}`);
  p(`  Forearm:            ${n(fore)}`);
  p(`  Hand span:          ${n(hand)}`);
  p(`  Shoulder width:     ${n(shoulders)}`);
  p(`  (compare a candidate's numbers to these + to signer data; smaller forearm = closer to a real signer)`);

  const suitable = handsComplete && has('leftHand') && has('rightHand');
  p(`\nVRM suitable for ISL: ${suitable ? 'YES' : 'NO'}${suitable ? '' : '  — fix the ✗ hand bones first; fingers are non-negotiable for signing'}`);
  if (suitable && !arkit) p(`  (usable, but add ARKit blendshapes if you want the captured face to drive it)`);
  p('');
  return { L, suitable };
}

// ---------- main ----------
const files = process.argv.slice(2);
if (!files.length) {
  console.error('usage: node scripts/validate-vrm.mjs <candidate.vrm> [more.vrm ...]');
  process.exit(2);
}
for (const f of files) {
  try { console.log(validate(f).L.join('\n')); }
  catch (e) { console.log(`\nAvatar: ${basename(f)}\n  ERROR: ${e.message}\n`); }
}
