"""
build_glb — bake ONE existing sign onto SMPL-X as a skinned, animated .glb.

    python offline/smplx/build_glb.py --sign we

Pipeline:
    public/skeleton/<sign>.json         (existing motion, UNCHANGED)
        -> skeleton_to_smplx (adapter)   positions -> SMPL-X local joint rotations
        -> SMPL-X rest mesh/skeleton     read straight from SMPLX_NEUTRAL.npz (numpy)
        -> skinned glTF                  rest mesh + skeleton + skin weights + anim
        -> public/smplx/<sign>.glb

The linear-blend-skinning "forward" runs in the BROWSER via standard glTF
skinning, so no torch/GPU is needed here. SMPL-X pose-corrective blendshapes are
omitted (documented in docs/SMPLX_EXPERIMENT.md).
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np
import pygltflib as g

import skeleton_to_smplx as adapter

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NPZ = ROOT / "pipeline" / ".models" / "smplx" / "SMPLX_NEUTRAL.npz"
DEFAULT_SKEL_DIR = ROOT / "public" / "skeleton"
DEFAULT_OUT_DIR = ROOT / "public" / "smplx"

# Signs where the two hands are MEANT to meet/cross. Hand clearance (which pushes
# the hands apart to stop interpenetration) fights those signs, so it is off for
# them — the hands meet as signed, and SMPL-X's large hands overlap a little at
# the meet, which is the honest cost of a hands-together sign on a realistic hand.
HANDS_MEET = {"we"}


def load_smplx(npz_path: Path):
    d = np.load(npz_path, allow_pickle=True)
    v_template = np.asarray(d["v_template"], np.float32)          # (V,3)
    faces = np.asarray(d["f"], np.uint32)                         # (Ntri,3)
    j_reg = np.asarray(d["J_regressor"], np.float32)              # (55,V)
    weights = np.asarray(d["weights"], np.float32)                # (V,55)
    parents = np.asarray(d["kintree_table"], np.int64)[0].copy()  # (55,)
    parents[parents > 1_000_000] = -1                             # root sentinel
    j_rest = (j_reg @ v_template).astype(np.float32)              # (55,3)
    return v_template, faces, weights, parents, j_rest


def vertex_normals(v, f):
    n = np.zeros_like(v)
    tri = v[f]                                   # (Ntri,3,3)
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln < 1e-12] = 1.0
    return (n / ln).astype(np.float32)


def top4_skin(weights):
    order = np.argsort(weights, axis=1)[:, -4:]          # 4 largest per vertex
    w4 = np.take_along_axis(weights, order, axis=1).astype(np.float32)
    s = w4.sum(axis=1, keepdims=True); s[s < 1e-12] = 1.0
    w4 = w4 / s
    return order.astype(np.uint8), w4                    # JOINTS_0, WEIGHTS_0


class Blob:
    """Accumulates the GLB binary chunk, one 4-byte-aligned bufferView at a time."""
    def __init__(self):
        self.buf = bytearray()
        self.views: list[g.BufferView] = []

    def add(self, data: bytes, target=None) -> int:
        while len(self.buf) % 4:
            self.buf += b"\x00"
        off = len(self.buf)
        self.buf += data
        self.views.append(g.BufferView(buffer=0, byteOffset=off, byteLength=len(data), target=target))
        return len(self.views) - 1


# Crop the body like the VRM signer: torso visible down to about the belt, no
# legs — but the hands stay, however low they hang. So we ALWAYS keep the arms,
# hands, neck and head (by skinning joint), and otherwise remove any vertex below
# the belt line. That drops the legs, pelvis and lower torso while never touching
# the hands (which are skinned to wrist/finger joints, not the torso).
KEEP_JOINTS = {12, 15, 16, 17, 18, 19, 20, 21} | set(range(25, 55))  # neck, head, arms, hands
BELT_Y = -0.22


def prepare_model(npz_path: Path, crop_lower: bool = True):
    """Load the sign-INDEPENDENT SMPL-X data once (mesh, skeleton, skin)."""
    v, f, weights, parents, j_rest = load_smplx(npz_path)
    if crop_lower:
        dominant = weights.argmax(axis=1)                              # (V,) each vertex's main joint
        keep = np.isin(dominant, list(KEEP_JOINTS)) | (v[:, 1] >= BELT_Y)  # arms/hands/head, or above belt
        f = f[keep[f].all(axis=1)]                                     # keep faces whose 3 verts are all kept
    joints0, weights0 = top4_skin(weights)
    return {
        "v": v, "f": f, "parents": parents, "j_rest": j_rest,
        "normals": vertex_normals(v, f), "joints0": joints0, "weights0": weights0,
    }


def build(sign: str, model: dict, skel_dir: Path, out_path: Path):
    v, f, parents, j_rest = model["v"], model["f"], model["parents"], model["j_rest"]
    normals, joints0, weights0 = model["normals"], model["joints0"], model["weights0"]
    NV = v.shape[0]

    sign_json = skel_dir / f"{sign}.json"
    times, quats, report = adapter.compute_rotations(
        sign_json, j_rest, parents, hand_clearance=(sign not in HANDS_MEET))
    F = times.shape[0]
    print(f"[build_glb] sign={sign} frames={F} fps={report['fps']:.0f} "
          f"driven={report['driven_joints']} self_check_mean_cos={report['self_check_mean_cos']:.4f}")
    if report["self_check_mean_cos"] is not None and report["self_check_mean_cos"] < 0.9:
        print("  WARNING: low self-check cosine — swing extraction / alignment may be off.")

    blob = Blob()
    # vertex attributes
    v_pos = blob.add(v.tobytes(), g.ARRAY_BUFFER)
    v_nrm = blob.add(normals.tobytes(), g.ARRAY_BUFFER)
    v_jnt = blob.add(joints0.tobytes(), g.ARRAY_BUFFER)
    v_wgt = blob.add(weights0.tobytes(), g.ARRAY_BUFFER)
    v_idx = blob.add(f.reshape(-1).astype(np.uint32).tobytes(), g.ELEMENT_ARRAY_BUFFER)
    # inverse bind matrices: translate(-J_rest[j]), column-major mat4
    ibm = np.tile(np.eye(4, dtype=np.float32), (adapter.NUM_JOINTS, 1, 1))
    ibm[:, 3, 0:3] = -j_rest                     # column-major: translation in row 3, cols 0..2
    v_ibm = blob.add(ibm.reshape(adapter.NUM_JOINTS, 16).tobytes())
    # animation input (times) + one rotation output per driven joint
    v_time = blob.add(times.tobytes())
    rot_views = {j: blob.add(np.ascontiguousarray(quats[:, j, :]).tobytes())
                 for j in adapter.DRIVEN_JOINT_INDICES}

    acc: list[g.Accessor] = []

    def accessor(view, ctype, count, atype, mn=None, mx=None, norm=None):
        acc.append(g.Accessor(bufferView=view, componentType=ctype, count=count, type=atype,
                              min=mn, max=mx, normalized=norm))
        return len(acc) - 1

    a_pos = accessor(v_pos, g.FLOAT, NV, g.VEC3, v.min(0).tolist(), v.max(0).tolist())
    a_nrm = accessor(v_nrm, g.FLOAT, NV, g.VEC3)
    a_jnt = accessor(v_jnt, g.UNSIGNED_BYTE, NV, g.VEC4, norm=False)
    a_wgt = accessor(v_wgt, g.FLOAT, NV, g.VEC4)
    a_idx = accessor(v_idx, g.UNSIGNED_INT, int(f.size), g.SCALAR)
    a_ibm = accessor(v_ibm, g.FLOAT, adapter.NUM_JOINTS, g.MAT4)
    a_time = accessor(v_time, g.FLOAT, F, g.SCALAR, [float(times[0])], [float(times[-1])])
    a_rot = {j: accessor(rot_views[j], g.FLOAT, F, g.VEC4) for j in adapter.DRIVEN_JOINT_INDICES}

    # nodes: 0..54 = joints (hierarchy from parents), 55 = skinned mesh node
    nodes: list[g.Node] = []
    for j in range(adapter.NUM_JOINTS):
        t = (j_rest[j] if parents[j] < 0 else j_rest[j] - j_rest[parents[j]]).tolist()
        children = [k for k in range(adapter.NUM_JOINTS) if parents[k] == j]
        nodes.append(g.Node(translation=t, children=children or None,
                            name=adapter.SMPLX_JOINT_NAMES[j]))
    mesh_node = len(nodes)
    nodes.append(g.Node(mesh=0, skin=0, name="smplx_mesh"))

    material = g.Material(
        name="smplx_neutral",
        pbrMetallicRoughness=g.PbrMetallicRoughness(
            baseColorFactor=[0.82, 0.82, 0.86, 1.0], metallicFactor=0.0, roughnessFactor=0.75),
        doubleSided=True,
    )
    mesh = g.Mesh(primitives=[g.Primitive(
        attributes=g.Attributes(POSITION=a_pos, NORMAL=a_nrm, JOINTS_0=a_jnt, WEIGHTS_0=a_wgt),
        indices=a_idx, material=0)])
    skin = g.Skin(inverseBindMatrices=a_ibm, joints=list(range(adapter.NUM_JOINTS)), skeleton=0)

    samplers, channels = [], []
    for j in adapter.DRIVEN_JOINT_INDICES:
        si = len(samplers)
        samplers.append(g.AnimationSampler(input=a_time, output=a_rot[j], interpolation="LINEAR"))
        channels.append(g.AnimationChannel(sampler=si, target=g.AnimationChannelTarget(node=j, path="rotation")))
    animation = g.Animation(name=sign, samplers=samplers, channels=channels)

    gltf = g.GLTF2(
        asset=g.Asset(generator="AvatarEngine-ISL offline/smplx", version="2.0"),
        scenes=[g.Scene(nodes=[0, mesh_node])], scene=0,
        nodes=nodes, meshes=[mesh], skins=[skin], materials=[material],
        animations=[animation], accessors=acc, bufferViews=blob.views,
        buffers=[g.Buffer(byteLength=len(blob.buf))],
    )
    gltf.set_binary_blob(bytes(blob.buf))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gltf.save_binary(str(out_path))

    # re-open to confirm it parses
    chk = g.GLTF2().load_binary(str(out_path))
    print(f"[build_glb] wrote {out_path}  ({out_path.stat().st_size/1e6:.2f} MB)")
    print(f"  verts={NV} tris={f.shape[0]} joints={adapter.NUM_JOINTS} "
          f"anim_channels={len(chk.animations[0].channels)} verified_reload=OK")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sign", default="we")
    ap.add_argument("--all", action="store_true", help="bake every sign in --skeleton-dir")
    ap.add_argument("--npz", type=Path, default=DEFAULT_NPZ)
    ap.add_argument("--skeleton-dir", type=Path, default=DEFAULT_SKEL_DIR)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    if not a.npz.exists():
        raise SystemExit(f"SMPL-X model not found: {a.npz}\n"
                         f"Place SMPLX_NEUTRAL.npz there (register at smplx.is.tue.mpg.de).")
    model = prepare_model(a.npz)  # loaded once, reused for every sign
    if a.all:
        signs = sorted(p.stem for p in a.skeleton_dir.glob("*.json"))
        print(f"[build_glb] baking {len(signs)} signs from {a.skeleton_dir}")
        rows = []
        for s in signs:
            r = build(s, model, a.skeleton_dir, DEFAULT_OUT_DIR / f"{s}.glb")
            rows.append((s, r["self_check_mean_cos"]))
        print("\n=== self-check (mean cosine, 1.0 = exact) ===")
        for s, c in rows:
            flag = "" if (c is not None and c > 0.99) else "  <-- CHECK"
            print(f"  {s:16s} {c:.4f}{flag}")
    else:
        out = a.out or (DEFAULT_OUT_DIR / f"{a.sign}.glb")
        build(a.sign, model, a.skeleton_dir, out)


if __name__ == "__main__":
    main()
