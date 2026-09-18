"""
skeleton_to_smplx — the SMPL-X ADAPTER.

Consumes the EXISTING motion representation (public/skeleton/<sign>.json, the
`source_skeleton.v1 -> view` format: 59 joint POSITIONS per frame, Y-up,
root-centred at the hips, unit = mean hip->head) and produces per-frame LOCAL
joint ROTATIONS for SMPL-X's 55-joint skeleton.

It does NOT modify the source, and it does NOT reimplement a new motion algorithm:
every step mirrors the VRM path so the experiment compares the two BODIES on
identical motion, not two converters —

  * swing extraction   (SkeletonRetargeter.ts): restDir -> obsDir local rotation
  * arm IK             (armIK.ts): solve the elbow so the WRIST lands on the
                       signer's target for SMPL-X's OWN arm lengths, since
                       copying angles onto a differently-proportioned arm moves
                       the hand off target
  * hand clearance     (handClearance.ts): push the two wrists apart along the
                       smoothed closest-pair axis until the hands stop
                       interpenetrating, then re-solve the elbows

Only the arms, hands and fingers are driven — torso, neck, head, legs and the
root are left at rest — matching the VRM path's DEFAULT. Twist about a bone's own
axis is not recovered (swing only); the wrist additionally recovers roll from an
across-the-knuckles axis, exactly as the VRM retargeter does. See
docs/SMPLX_EXPERIMENT.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# ----------------------------------------------------------------------------
# SMPL-X joint order (55), decoded from kintree_table in SMPLX_NEUTRAL.npz.
# ----------------------------------------------------------------------------
SMPLX_JOINT_NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee",       # 0-5
    "spine2", "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot",   # 6-11
    "neck", "left_collar", "right_collar", "head",                                # 12-15
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",               # 16-19
    "left_wrist", "right_wrist", "jaw", "left_eye", "right_eye",                  # 20-24
    "left_index1", "left_index2", "left_index3",                                  # 25-27
    "left_middle1", "left_middle2", "left_middle3",                               # 28-30
    "left_pinky1", "left_pinky2", "left_pinky3",                                  # 31-33
    "left_ring1", "left_ring2", "left_ring3",                                     # 34-36
    "left_thumb1", "left_thumb2", "left_thumb3",                                  # 37-39
    "right_index1", "right_index2", "right_index3",                              # 40-42
    "right_middle1", "right_middle2", "right_middle3",                           # 43-45
    "right_pinky1", "right_pinky2", "right_pinky3",                              # 46-48
    "right_ring1", "right_ring2", "right_ring3",                                 # 49-51
    "right_thumb1", "right_thumb2", "right_thumb3",                              # 52-54
]
IDX = {n: i for i, n in enumerate(SMPLX_JOINT_NAMES)}
NUM_JOINTS = len(SMPLX_JOINT_NAMES)  # 55


class Drive:
    """One driven SMPL-X bone. Mirrors SkeletonRetargeter.Drive."""
    __slots__ = ("joint", "rest_child", "rest_from_parent", "src_from", "src_to",
                 "across_from", "across_to", "rest_across_from", "rest_across_to")

    def __init__(self, joint, rest_child, src_from, src_to, rest_from_parent=False,
                 across_from=None, across_to=None, rest_across_from=None, rest_across_to=None):
        self.joint = IDX[joint]
        self.rest_child = IDX[rest_child] if rest_child else None
        self.rest_from_parent = rest_from_parent
        self.src_from = src_from
        self.src_to = src_to
        self.across_from = across_from
        self.across_to = across_to
        self.rest_across_from = IDX[rest_across_from] if rest_across_from else None
        self.rest_across_to = IDX[rest_across_to] if rest_across_to else None


def _side_drives(side: str, p: str) -> list[Drive]:
    """side='left'|'right', p='l'|'r'. SMPL-X hand order is index, middle, PINKY, ring, thumb."""
    S = lambda n: f"{side}_{n}"
    return [
        Drive(S("shoulder"), S("elbow"), f"{p}Shoulder", f"{p}Elbow"),
        Drive(S("elbow"), S("wrist"), f"{p}Elbow", f"{p}Wrist"),
        Drive(S("wrist"), S("middle1"), f"{p}Hand", f"{p}Middle1",
              across_from=f"{p}Index1", across_to=f"{p}Pinky1",
              rest_across_from=S("index1"), rest_across_to=S("pinky1")),
        Drive(S("index1"), S("index2"), f"{p}Index1", f"{p}Index2"),
        Drive(S("index2"), S("index3"), f"{p}Index2", f"{p}Index3"),
        Drive(S("index3"), None, f"{p}Index3", f"{p}Index4", rest_from_parent=True),
        Drive(S("middle1"), S("middle2"), f"{p}Middle1", f"{p}Middle2"),
        Drive(S("middle2"), S("middle3"), f"{p}Middle2", f"{p}Middle3"),
        Drive(S("middle3"), None, f"{p}Middle3", f"{p}Middle4", rest_from_parent=True),
        Drive(S("ring1"), S("ring2"), f"{p}Ring1", f"{p}Ring2"),
        Drive(S("ring2"), S("ring3"), f"{p}Ring2", f"{p}Ring3"),
        Drive(S("ring3"), None, f"{p}Ring3", f"{p}Ring4", rest_from_parent=True),
        Drive(S("pinky1"), S("pinky2"), f"{p}Pinky1", f"{p}Pinky2"),
        Drive(S("pinky2"), S("pinky3"), f"{p}Pinky2", f"{p}Pinky3"),
        Drive(S("pinky3"), None, f"{p}Pinky3", f"{p}Pinky4", rest_from_parent=True),
        Drive(S("thumb1"), S("thumb2"), f"{p}Thumb1", f"{p}Thumb2"),
    ]


DRIVES: list[Drive] = _side_drives("left", "l") + _side_drives("right", "r")
DRIVEN_JOINT_INDICES = sorted({d.joint for d in DRIVES})
_DRIVE_BY_JOINT = {d.joint: d for d in DRIVES}

# Per-side arm chain (shoulder -> elbow -> wrist/hand) for IK + clearance.
ARM = {
    "l": {"shoulder": IDX["left_shoulder"], "elbow": IDX["left_elbow"], "wrist": IDX["left_wrist"], "sign": +1.0},
    "r": {"shoulder": IDX["right_shoulder"], "elbow": IDX["right_elbow"], "wrist": IDX["right_wrist"], "sign": -1.0},
}
ARM_DRIVES = {s: [_DRIVE_BY_JOINT[ARM[s]["shoulder"]], _DRIVE_BY_JOINT[ARM[s]["elbow"]], _DRIVE_BY_JOINT[ARM[s]["wrist"]]] for s in "lr"}
ELBOW_SRC = {"lElbow": "l", "rElbow": "r"}   # which side's IK elbow a source name maps to

# Hand bones used as collision points (wrist + all finger joints), and the distal
# joints whose tips are extended (a fingertip is not a bone).
HAND_COLLISION = {"l": [IDX["left_wrist"]] + list(range(25, 40)),
                  "r": [IDX["right_wrist"]] + list(range(40, 55))}
DISTAL_TIPS = {"l": [IDX["left_index3"], IDX["left_middle3"], IDX["left_pinky3"], IDX["left_ring3"], IDX["left_thumb3"]],
               "r": [IDX["right_index3"], IDX["right_middle3"], IDX["right_pinky3"], IDX["right_ring3"], IDX["right_thumb3"]]}
# Adjacent knuckles across the palm (index-middle, middle-ring, ring-pinky), for sizing clearance.
KNUCKLE_PAIRS = [(IDX["left_index1"], IDX["left_middle1"]),
                 (IDX["left_middle1"], IDX["left_ring1"]),
                 (IDX["left_ring1"], IDX["left_pinky1"])]

AXIS_FOLLOW = 0.25       # handClearance.ts
# SkeletonRetargeter caps at 0.09 (hip->head units); SMPL-X's realistic hands are
# larger and interleave more deeply on crossing signs, so clearing them needs a
# bigger push — raised to 0.13. The push is depth-dominant (the axis the camera
# could not measure), so it is far less visible than its size suggests.
MAX_PUSH = 0.13

# Temporal smoothing (zero-phase slerp EMA), the offline analogue of the signer's
# fingerSmoothing. Fingers are noisiest — short segments amplify capture noise —
# so they smooth harder than the arms. Lower = smoother; 1.0 = off.
FINGER_SMOOTH_JOINTS = set(range(25, NUM_JOINTS))
ARM_SMOOTH_JOINTS = {IDX["left_shoulder"], IDX["right_shoulder"], IDX["left_elbow"],
                     IDX["right_elbow"], IDX["left_wrist"], IDX["right_wrist"]}
# Chosen for a clear calm-down without washing out the sign: on we this removes
# ~59% of the fingertip jitter while keeping ~86% of the range of motion. The arm
# smooths harder than the fingers because the wrist carries the whole hand, so
# wrist jitter shakes the fingertips regardless of how much the fingers smooth.
SMOOTH_FINGER = 0.22
SMOOTH_ARM = 0.30


# ----------------------------------------------------------------------------
# quaternion / vector maths (xyzw, matching three.js & glTF). No scipy/torch.
# ----------------------------------------------------------------------------
def _norm(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def quat_from_unit_vectors(a, b):
    a = _norm(np.asarray(a, float)); b = _norm(np.asarray(b, float))
    r = float(np.dot(a, b)) + 1.0
    if r < 1e-8:
        r = 0.0
        v = np.array([-a[1], a[0], 0.0]) if abs(a[0]) > abs(a[2]) else np.array([0.0, -a[2], a[1]])
    else:
        v = np.cross(a, b)
    q = np.array([v[0], v[1], v[2], r])
    n = np.linalg.norm(q)
    return q / n if n > 1e-12 else np.array([0.0, 0.0, 0.0, 1.0])


def quat_mul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ])


def quat_inv(q):
    return np.array([-q[0], -q[1], -q[2], q[3]])


def quat_rotate(q, v):
    qv = q[:3]
    t = 2.0 * np.cross(qv, v)
    return v + q[3] * t + np.cross(qv, t)


def slerp(q0, q1, t):
    q0 = _norm(q0); q1 = np.asarray(q1, float)
    dot = float(np.dot(q0, q1))
    if dot < 0:
        q1 = -q1; dot = -dot
    if dot > 0.9995:
        return _norm(q0 + t * (q1 - q0))
    theta = np.arccos(dot); st = np.sin(theta)
    return (np.sin((1 - t) * theta) / st) * q0 + (np.sin(t * theta) / st) * q1


def smooth_series(qs, alpha):
    """Zero-phase temporal smoothing of a quaternion series (F,4): a slerp EMA run
    forward then backward, so it removes jitter without the lag a causal filter
    adds. alpha in (0,1] = responsiveness; lower is smoother, 1 is off."""
    if alpha >= 1.0 or len(qs) < 3:
        return qs
    out = [q.copy() for q in qs]
    for i in range(1, len(out)):
        out[i] = slerp(out[i - 1], out[i], alpha)
    for i in range(len(out) - 2, -1, -1):
        out[i] = slerp(out[i + 1], out[i], alpha)
    return np.array(out)


def _quat_from_matrix(m):
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = 0.5 / np.sqrt(t + 1.0)
        return _norm(np.array([(m[2, 1] - m[1, 2]) * s, (m[0, 2] - m[2, 0]) * s, (m[1, 0] - m[0, 1]) * s, 0.25 / s]))
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        return _norm(np.array([0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]))
    if m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        return _norm(np.array([(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]))
    s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
    return _norm(np.array([(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]))


def _basis_quat(primary, secondary):
    x = _norm(primary)
    z = np.cross(x, secondary)
    if float(np.dot(z, z)) < 1e-10:
        return None
    z = _norm(z)
    y = _norm(np.cross(z, x))
    return _quat_from_matrix(np.column_stack([x, y, z]))


def _orientation_between(rp, rs, op, os):
    qr = _basis_quat(rp, rs); qo = _basis_quat(op, os)
    if qr is None or qo is None:
        return None
    return quat_mul(qo, quat_inv(qr))


# ----------------------------------------------------------------------------
# arm IK (armIK.ts) + hand clearance (handClearance.ts), ported to numpy.
# ----------------------------------------------------------------------------
def solve_elbow(shoulder, target, hint, upper, fore):
    """Elbow position that puts the wrist on `target`; `hint` chooses the swivel."""
    d = target - shoulder
    reach = upper + fore
    dist = float(np.linalg.norm(d))
    n = np.array([0.0, -1.0, 0.0]) if dist < 1e-6 else d / dist
    clamped = min(max(dist, abs(upper - fore) + 1e-5), reach - 1e-5)
    cos = (upper * upper + clamped * clamped - fore * fore) / (2 * upper * clamped)
    angle = np.arccos(min(1.0, max(-1.0, cos)))
    h = (hint - shoulder)
    h = h - n * float(np.dot(h, n))
    if float(np.dot(h, h)) < 1e-10:
        h = np.array([-n[1], n[0], 0.0])
        if float(np.dot(h, h)) < 1e-10:
            h = np.array([0.0, -n[2], n[1]])
    h = _norm(h)
    return shoulder + n * (np.cos(angle) * upper) + h * (np.sin(angle) * upper)


def closest_pair_axis(left, right, within):
    """Unit direction of the closest left/right pair (right->left), or None."""
    best = within * within
    out = None
    for a in left:
        for b in right:
            dd = a - b
            d2 = float(np.dot(dd, dd))
            if d2 >= best or d2 < 1e-12:
                continue
            best = d2
            out = dd
    return _norm(out) if out is not None else None


def push_to_clear(left, right, axis, clearance, cap):
    """Smallest symmetric push along `axis` holding every pair >= clearance (capped)."""
    c2 = clearance * clearance
    delta = 0.0
    for _ in range(8):
        moved = False
        for a in left:
            for b in right:
                dvec = a - b
                du = float(np.dot(dvec, axis))
                disc = du * du - float(np.dot(dvec, dvec)) + c2
                if disc <= 0:
                    continue
                root = np.sqrt(disc)
                hi = root - du
                if delta >= hi or delta <= -root - du:
                    continue
                delta = hi
                moved = True
                if delta >= cap:
                    return cap
        if not moved:
            break
    return delta if delta < cap else cap


# ----------------------------------------------------------------------------
# coordinate alignment: source "view" frame -> SMPL-X rest frame.
# ----------------------------------------------------------------------------
def _anatomical_basis(up, lateral):
    up = _norm(up)
    fwd = _norm(np.cross(up, lateral))
    lat = _norm(np.cross(fwd, up))
    return np.column_stack([lat, up, fwd])


def compute_alignment(source_frames, j_rest):
    def mean_pos(name):
        return np.mean([f["joints"][name][:3] for f in source_frames], axis=0)
    Mv = _anatomical_basis(mean_pos("head") - mean_pos("hips"), mean_pos("rShoulder") - mean_pos("lShoulder"))
    Ms = _anatomical_basis(j_rest[IDX["head"]] - j_rest[IDX["pelvis"]],
                           j_rest[IDX["right_shoulder"]] - j_rest[IDX["left_shoulder"]])
    return Ms @ Mv.T


# ----------------------------------------------------------------------------
# main entry: source json + SMPL-X rest joints + parents -> per-frame rotations
# ----------------------------------------------------------------------------
def compute_rotations(sign_json_path, j_rest, parents, arm_ik=True, hand_clearance=True, smooth=True):
    """Return (times[F], quats[F,55,4] xyzw LOCAL rotations, report dict).

    Undriven joints get identity. Mirrors SkeletonRetargeter.applyPose: swing
    extraction, then armIK on the elbow, then a hand-clearance push + re-solve.
    """
    data = json.loads(Path(sign_json_path).read_text())
    frames = data["frames"]
    fps = float(data["meta"]["fps"])
    F = len(frames)
    R_align = compute_alignment(frames, j_rest)

    span = float(np.linalg.norm(j_rest[IDX["head"]] - j_rest[IDX["pelvis"]])) or 1.0
    # SMPL-X geometry in hip->head units, so it shares one ruler with the capture.
    rest_local = {j: (j_rest[j] - j_rest[parents[j]]) / span for j in range(NUM_JOINTS) if parents[j] >= 0}
    arm_len = {s: (float(np.linalg.norm(j_rest[ARM[s]["shoulder"]] - j_rest[ARM[s]["elbow"]])) / span,
                   float(np.linalg.norm(j_rest[ARM[s]["elbow"]] - j_rest[ARM[s]["wrist"]])) / span) for s in "lr"}
    knuckle = np.mean([np.linalg.norm(j_rest[a] - j_rest[b]) / span for a, b in KNUCKLE_PAIRS])
    clearance = 1.35 * float(knuckle)

    # rest directions (world == parent-local at rest, all rest rotations identity)
    rest_dir, rest_across = {}, {}
    for d in DRIVES:
        rest_dir[d.joint] = _norm(j_rest[d.joint] - j_rest[parents[d.joint]]) if d.rest_from_parent \
            else _norm(j_rest[d.rest_child] - j_rest[d.joint])
        if d.rest_across_from is not None:
            rest_across[d.joint] = _norm(j_rest[d.rest_across_to] - j_rest[d.rest_across_from])

    identity = np.array([0.0, 0.0, 0.0, 1.0])
    quats = np.tile(identity, (F, NUM_JOINTS, 1))
    push_axis = None
    cos_sum, cos_n, clear_frames = 0.0, 0, 0
    deltas = []

    def bone_rotation(d, Rparent, pos):
        a = pos(d.src_from); b = pos(d.src_to)
        rest = rest_dir[d.joint]
        if a is None or b is None:
            return None
        seg = b - a
        if float(np.dot(seg, seg)) < 1e-10:
            return None
        inv = quat_inv(Rparent)
        obs_local = _norm(quat_rotate(inv, seg))
        q = quat_from_unit_vectors(rest, obs_local)
        ra = rest_across.get(d.joint)
        if ra is not None and d.across_from and d.across_to:
            aa = pos(d.across_from); ab = pos(d.across_to)
            if aa is not None and ab is not None:
                full = _orientation_between(rest, ra, obs_local, quat_rotate(inv, ab - aa))
                if full is not None:
                    q = full
        return q, _norm(seg)  # second value is the WORLD observed direction, for the self-check

    for fi, frame in enumerate(frames):
        J = frame["joints"]
        aligned = {name: R_align @ np.asarray(v[:3], float) for name, v in J.items()}

        # IK elbows (armIK): solve so the wrist lands on the observed target.
        ik = {}
        if arm_ik:
            for s in "lr":
                sh = aligned.get(f"{s}Shoulder"); el = aligned.get(f"{s}Elbow"); wr = aligned.get(f"{s}Wrist")
                if sh is not None and el is not None and wr is not None:
                    ik[s] = solve_elbow(sh, wr, el, *arm_len[s])

        def pos(name, _ik=ik, _al=aligned):
            side = ELBOW_SRC.get(name)
            if side is not None and side in _ik:
                return _ik[side]
            return _al.get(name)

        Rworld = [identity] * NUM_JOINTS
        for d in DRIVES:
            Rp = Rworld[parents[d.joint]] if parents[d.joint] >= 0 else identity
            res = bone_rotation(d, Rp, pos)
            if res is None:
                Rworld[d.joint] = Rp
                continue
            q, world_dir = res
            quats[fi, d.joint] = q
            Rworld[d.joint] = quat_mul(Rp, q)
            posed = quat_rotate(Rworld[d.joint], rest_dir[d.joint])
            cos_sum += float(np.dot(_norm(posed), world_dir)); cos_n += 1  # == 1 by construction

        # Hand clearance: FK the hands, push the wrists apart, re-solve the arms.
        if hand_clearance:
            fk_cache = {}

            def fk(bone):
                if bone in fk_cache:
                    return fk_cache[bone]
                par = parents[bone]
                base = np.zeros(3) if par < 0 else fk(par)
                off = rest_local.get(bone)
                out = base if (par < 0 or off is None) else base + quat_rotate(Rworld[par], off)
                fk_cache[bone] = out
                return out

            def hand_points(side):
                pts = []
                for bone in HAND_COLLISION[side]:
                    p = fk(bone)
                    pts.append(p)
                    if bone in DISTAL_TIPS[side] and bone in rest_local:
                        pts.append(p + quat_rotate(Rworld[bone], rest_local[bone]))  # extend distal -> tip
                return pts

            left, right = hand_points("l"), hand_points("r")
            raw = closest_pair_axis(left, right, clearance)
            if raw is None:
                push_axis = None
            else:
                if push_axis is None:
                    push_axis = raw.copy()
                else:
                    push_axis = push_axis * (1 - AXIS_FOLLOW) + raw * AXIS_FOLLOW
                    push_axis = raw.copy() if float(np.dot(push_axis, push_axis)) < 0.01 else _norm(push_axis)
                delta = push_to_clear(left, right, push_axis, clearance, MAX_PUSH)
                deltas.append(delta)
                if delta > 0 and arm_ik:
                    clear_frames += 1
                    for s in "lr":
                        sh = aligned.get(f"{s}Shoulder"); wr = aligned.get(f"{s}Wrist")
                        if sh is None or wr is None:
                            continue
                        target = wr + push_axis * (ARM[s]["sign"] * delta / 2)
                        elbow = solve_elbow(sh, target, ik.get(s, aligned.get(f"{s}Elbow", sh)), *arm_len[s])
                        moved = {f"{s}Elbow": elbow, f"{s}Wrist": target}
                        posf = lambda name, _m=moved, _al=aligned: _m.get(name, _al.get(name))
                        Rp = Rworld[parents[ARM[s]["shoulder"]]] if parents[ARM[s]["shoulder"]] >= 0 else identity
                        for d in ARM_DRIVES[s]:
                            res = bone_rotation(d, Rp, posf)
                            if res is None:
                                Rp = Rworld[d.joint]
                                continue
                            quats[fi, d.joint] = res[0]
                            Rp = quat_mul(Rp, res[0])
                            Rworld[d.joint] = Rp

    # Temporal smoothing pass — kills the per-frame jitter (finger-depth noise and
    # the clearance push switching on and off between frames). Zero-phase, so the
    # motion is not delayed. Runs on the FINAL rotations, after IK + clearance.
    if smooth:
        for j in DRIVEN_JOINT_INDICES:
            a = SMOOTH_FINGER if j in FINGER_SMOOTH_JOINTS else SMOOTH_ARM
            quats[:, j, :] = smooth_series(quats[:, j, :], a)

    report = {
        "frames": F, "fps": fps, "driven_joints": len(DRIVES),
        "self_check_mean_cos": (cos_sum / cos_n) if cos_n else None,
        "arm_ik": arm_ik, "hand_clearance": hand_clearance,
        "clearance_frames": clear_frames, "clearance_units": round(clearance, 4),
        "mean_push": round(float(np.mean([d for d in deltas if d > 0])), 4) if any(d > 0 for d in deltas) else 0.0,
    }
    times = (np.arange(F, dtype=np.float32) / fps)
    return times, quats.astype(np.float32), report
