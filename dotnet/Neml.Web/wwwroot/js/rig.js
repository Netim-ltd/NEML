// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Forward kinematics of an imported robot: the joint tree the lab publishes (scene.rig, millimetres,
// quaternions [x, y, z, w]) posed at given joint values. Pure maths on flat row-major 4x4 matrices,
// no THREE: the same arithmetic as brain/neml_brain/evolution/urdf_assembly.py `link_matrices`,
// and tests compare the two (brain/tests/evolution/test_rig_js.py).

export const identity = () => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

export function multiply(a, b) {
    const out = new Array(16).fill(0);
    for (let r = 0; r < 4; r++) {
        for (let c = 0; c < 4; c++) {
            for (let k = 0; k < 4; k++) out[r * 4 + c] += a[r * 4 + k] * b[k * 4 + c];
        }
    }
    return out;
}

export function fromQuaternion(q, p) {
    const [x, y, z, w] = q;
    return [
        1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), p[0],
        2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), p[1],
        2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), p[2],
        0, 0, 0, 1,
    ];
}

/** What a joint adds at `value`: radians about its axis (revolute, continuous), metres along it (prismatic). */
export function motion(joint, value) {
    const m = identity();
    const [x, y, z] = joint.axis;
    if (joint.type === 'revolute' || joint.type === 'continuous') {
        const c = Math.cos(value);
        const s = Math.sin(value);
        m[0] = c + x * x * (1 - c); m[1] = x * y * (1 - c) - z * s; m[2] = x * z * (1 - c) + y * s;
        m[4] = y * x * (1 - c) + z * s; m[5] = c + y * y * (1 - c); m[6] = y * z * (1 - c) - x * s;
        m[8] = z * x * (1 - c) - y * s; m[9] = z * y * (1 - c) + x * s; m[10] = c + z * z * (1 - c);
    } else if (joint.type === 'prismatic') {
        m[3] = x * value * 1000; m[7] = y * value * 1000; m[11] = z * value * 1000;
    }
    return m;
}

/** World matrix of every link: Map link name -> matrix. `values` maps joint name -> radians (metres). */
export function linkMatrices(rig, values = {}) {
    const byChild = new Map(rig.joints.map((j) => [j.child, j]));
    const byName = new Map(rig.joints.map((j) => [j.name, j]));
    const world = new Map([[rig.root, identity()]]);
    const valueOf = (joint, depth = 0) => {
        const m = joint.mimic;
        if (m && depth < 8) {
            const other = byName.get(m.joint);
            return m.multiplier * (other ? valueOf(other, depth + 1) : 0) + m.offset;
        }
        return values[joint.name] ?? 0;
    };
    const pose = (link, seen = []) => {
        if (world.has(link)) return world.get(link);
        const joint = byChild.get(link);
        if (!joint || seen.includes(link)) { world.set(link, identity()); return world.get(link); }
        const origin = fromQuaternion(joint.quat, joint.pos);
        world.set(link, multiply(multiply(pose(joint.parent, [...seen, link]), origin), motion(joint, valueOf(joint))));
        return world.get(link);
    };
    rig.joints.forEach((j) => pose(j.child));
    return world;
}

/** World matrix of a part: its link's matrix times the part's pose in the link frame. */
export function partMatrix(linkMatrix, local) {
    return multiply(linkMatrix, fromQuaternion(local.quat, local.pos));
}

/** Joints the operator can move: not fixed, not following another joint. */
export const movable = (rig) => rig.joints.filter((j) => !j.mimic && ['revolute', 'continuous', 'prismatic'].includes(j.type));
