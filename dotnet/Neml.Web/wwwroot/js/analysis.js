// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// What a pose means physically, from the parts' boxes: which parts run into each other, where the
// centre of mass is, and whether the robot would stand (the centre of mass over the support polygon
// of the lowest points). Pure maths on plain arrays (millimetres, quaternions [x, y, z, w]); the
// boxes are the parts' oriented bounding boxes, so a result is a conservative estimate, not a mesh
// test: tests in brain/tests/evolution/test_analysis_js.py pin the behaviour.

export function rotationOf([x, y, z, w]) {
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ];
}

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const column = (r, i) => [r[0][i], r[1][i], r[2][i]];

/** Corners of an oriented box {c, q, h}. */
export function corners(box) {
    const r = rotationOf(box.q);
    const out = [];
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
        out.push([0, 1, 2].map((k) => box.c[k] + r[k][0] * box.h[0] * sx + r[k][1] * box.h[1] * sy + r[k][2] * box.h[2] * sz));
    }
    return out;
}

/**
 * Penetration depth of two oriented boxes by the separating axis test: the smallest overlap along
 * any axis, <= 0 when they are apart. Boxes are shrunk a little so touching parts do not count.
 */
export function depth(a, b, shrink = 0.97) {
    const ra = rotationOf(a.q);
    const rb = rotationOf(b.q);
    const ha = a.h.map((v) => v * shrink);
    const hb = b.h.map((v) => v * shrink);
    const ea = [0, 1, 2].map((i) => column(ra, i));
    const eb = [0, 1, 2].map((i) => column(rb, i));
    const d = [b.c[0] - a.c[0], b.c[1] - a.c[1], b.c[2] - a.c[2]];
    const axes = [...ea, ...eb];
    for (const u of ea) for (const v of eb) {
        const c = cross(u, v);
        if (dot(c, c) > 1e-9) axes.push(c);
    }
    let least = Infinity;
    for (const axis of axes) {
        const length = Math.sqrt(dot(axis, axis));
        const n = axis.map((v) => v / length);
        const pa = ha.reduce((s, h, i) => s + h * Math.abs(dot(n, ea[i])), 0);
        const pb = hb.reduce((s, h, i) => s + h * Math.abs(dot(n, eb[i])), 0);
        least = Math.min(least, pa + pb - Math.abs(dot(n, d)));
        if (least <= 0) return least;
    }
    return least;
}

/** Do two oriented boxes share volume (any depth)? */
export function overlap(a, b, shrink = 0.97) {
    return depth(a, b, shrink) > 0;
}

/**
 * Links welded together by fixed joints move as one rigid body: Map link -> group id (the first link
 * of the group). Parts of one rigid body never "collide" with each other.
 */
export function rigidGroups(rig) {
    const parent = new Map();
    const find = (x) => { if (!parent.has(x)) parent.set(x, x); while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
    rig.joints.forEach((j) => { find(j.parent); find(j.child); });
    rig.joints.filter((j) => j.type === 'fixed').forEach((j) => parent.set(find(j.child), find(j.parent)));
    const groups = new Map();
    for (const link of parent.keys()) groups.set(link, find(link));
    return groups;
}

/** Pairs of rigid groups that a moving joint connects: neighbours that are meant to touch. */
export function groupNeighbours(rig, groups) {
    return rig.joints.filter((j) => j.type !== 'fixed').map((j) => [groups.get(j.parent), groups.get(j.child)]);
}

/**
 * Pairs of parts that run into each other by more than `minDepth` mm. `items` are {id, link, box}
 * (`link` is a rigid group id); parts of the same group and of neighbouring groups (a moving
 * joint between them) are meant to touch and are skipped.
 */
export function collisions(items, neighbours, minDepth = 2.5) {
    const near = new Set(neighbours.map(([a, b]) => `${a}|${b}`).concat(neighbours.map(([a, b]) => `${b}|${a}`)));
    const hits = [];
    for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
            const a = items[i];
            const b = items[j];
            if (a.link && b.link && (a.link === b.link || near.has(`${a.link}|${b.link}`))) continue;
            if (depth(a.box, b.box) > minDepth) hits.push([a.id, b.id]);
        }
    }
    return hits;
}

/** Mass-weighted centre of {m, p}; null without any mass. */
export function centreOfMass(points) {
    const total = points.reduce((s, q) => s + q.m, 0);
    if (!(total > 0)) return null;
    return { mass: total, p: [0, 1, 2].map((k) => points.reduce((s, q) => s + q.m * q.p[k], 0) / total) };
}

/** Convex hull (monotone chain) of 2D points; counter-clockwise, no repeated first point. */
export function hull2d(points) {
    const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const unique = pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1][0] || p[1] !== pts[i - 1][1]);
    if (unique.length < 3) return unique;
    const turn = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const build = (list) => {
        const out = [];
        for (const p of list) {
            while (out.length >= 2 && turn(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop();
            out.push(p);
        }
        out.pop();
        return out;
    };
    return [...build(unique), ...build([...unique].reverse())];
}

/** Signed distance of a point inside a counter-clockwise hull to its nearest edge: positive inside, negative outside. */
export function insideMargin(point, hull) {
    if (hull.length < 3) return -Infinity;
    let margin = Infinity;
    for (let i = 0; i < hull.length; i++) {
        const a = hull[i];
        const b = hull[(i + 1) % hull.length];
        const ex = b[0] - a[0];
        const ey = b[1] - a[1];
        const length = Math.hypot(ex, ey) || 1;
        margin = Math.min(margin, (ex * (point[1] - a[1]) - ey * (point[0] - a[0])) / length);
    }
    return margin;
}

/**
 * Would the robot stand: the lowest points (within `tolerance` of the lowest one) are the ground
 * contacts, their hull is the support polygon, and the centre of mass must project inside it.
 */
export function stabilityOfPoints(points, com, tolerance = 4) {
    if (!points.length || !com) return null;
    const ground = Math.min(...points.map((p) => p[2]));
    const contacts = points.filter((p) => p[2] <= ground + tolerance).map((p) => [p[0], p[1]]);
    const hull = hull2d(contacts);
    const margin = insideMargin([com[0], com[1]], hull);
    return { ground, hull, margin, stable: margin > 0, height: com[2] - ground };
}

/** The same from oriented boxes (their corners are the points): a coarse estimate. */
export function stability(boxes, com, tolerance = 5) {
    return stabilityOfPoints(boxes.flatMap(corners), com, tolerance);
}
