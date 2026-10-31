// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Which screw holds what to what, and where: the assembly plan shown next to the 3D view. Pure
// maths (millimetres). Our printed parts carry their real hole centres (`holes`: [x, y, z, tag]
// around the part's centre, from the CAD template); screws go exactly there. Parts without hole
// data fall back to the box corners. Imported robots have no hole data: where two parts that a
// fixed joint welds touch, the screws go at the corners of the contact patch; a moving joint is a
// servo mount at the joint origin.
import { linkMatrices } from './rig.js';
import { corners as boxCorners } from './analysis.js';

const corners = (cx, cy, hx, hy) => [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => [cx + sx * hx, cy + sy * hy]);

/** Rotate by three.js Euler XYZ (degrees) and move: a part's local point -> scene point. */
export function toWorld(part, [x, y, z]) {
    const [a, b, c] = (part.rot || [0, 0, 0]).map((d) => (d * Math.PI) / 180);
    const [sa, ca, sb, cb, sc, cc] = [Math.sin(a), Math.cos(a), Math.sin(b), Math.cos(b), Math.sin(c), Math.cos(c)];
    const z1 = [x * cc - y * sc, x * sc + y * cc, z]; // Rz
    const y1 = [z1[0] * cb + z1[2] * sb, z1[1], -z1[0] * sb + z1[2] * cb]; // Ry
    const x1 = [y1[0], y1[1] * ca - y1[2] * sa, y1[1] * sa + y1[2] * ca]; // Rx
    return [x1[0] + part.pos[0], x1[1] + part.pos[1], x1[2] + part.pos[2]];
}

/** @returns {{step:number, part:string, host:string, screw:string, qty:number, at:number[][], note:string}[]} */
export function fastenerPlan(scene, boxes = null) {
    const parts = new Map(scene.parts.map((p) => [p.id, p]));
    const imported = scene.imported || (scene.rig && scene.rig.joints.length > 0 && !parts.has('shell_lower') && !parts.has('shell'));
    if (imported) return importedPlan(scene, boxes);

    const plan = [];
    const add = (part, host, screw, at, note) => at.length && plan.push({ step: plan.length + 1, part, host, screw, qty: at.length, at, note });
    const size = (p) => (p.geom && p.geom.size) || [0, 0, 0];
    const real = (p, tag) => (p.holes || []).filter((h) => h[3] === tag).map((h) => toWorld(p, h));

    const lower = parts.get('shell_lower') || parts.get('shell');
    const upper = parts.get('shell_upper');
    const inset = (p, d) => [size(p)[0] / 2 - d, size(p)[1] / 2 - d];
    if (lower && upper) {
        const at = real(upper, 'own');
        const [hx, hy] = inset(lower, 7.5);
        add('shell_upper', 'shell_lower', 'M3×10 vida',
            at.length ? at : corners(0, 0, hx, hy).map(([x, y]) => [x, y, upper.pos[2] + size(upper)[2] / 2]),
            'Üst yarı ters basılıdır; köşe kolonlarından alt yarıdaki M3 ısıl dişli takozlara vidalanır.');
    }

    const body = lower ? lower.id : null;
    for (const p of scene.parts) {
        const [sx] = size(p);
        const z = p.pos[2];
        const own = real(p, 'own');
        if (p.id === 'battery_tray' && body) {
            const [hx, hy] = inset(p, 5);
            add(p.id, body, 'M3×8 vida', own.length ? own : corners(p.pos[0], p.pos[1], hx, hy).map(([x, y]) => [x, y, z]), 'Alt yarının tabanına köşelerden; sonra bataryayı yatağa yerleştir.');
        } else if (p.id === 'board_plate' && body) {
            const [hx, hy] = inset(p, 4.5);
            add(p.id, body, 'M3×8 vida', own.length ? own : corners(p.pos[0], p.pos[1], hx, hy).map(([x, y]) => [x, y, z]), 'Plakanın köşe delikleri (3,2 mm) gövdeye.');
        } else if (p.id === 'compute' && parts.get('board_plate')) {
            const plate = parts.get('board_plate');
            const posts = real(plate, 'board');
            add(p.id, 'board_plate', 'M2.5×6 vida + ayırıcı',
                posts.length ? posts : corners(plate.pos[0], plate.pos[1], 29, 24.5).map(([x, y]) => [x, y, plate.pos[2] + size(plate)[2] / 2]),
                'Kartın kendi delik düzeni (58×49 mm); plakadaki ısıl dişli takozlara.');
        } else if (p.id.startsWith('bracket_') && body) {
            add(p.id, body, 'M3×10 vida', own.length ? own : [[p.pos[0] - sx / 2 + 5, p.pos[1], z], [p.pos[0] + sx / 2 - 5, p.pos[1], z]], 'İki vida kulağı gövde çerçevesine.');
        }
    }
    return plan;
}

/** Corners of the patch where the boxes of two link groups touch (null when they do not). */
function contact(a, b) {
    const span = (boxesOf) => {
        const pts = boxesOf.flatMap(boxCorners);
        return [0, 1, 2].map((k) => [Math.min(...pts.map((p) => p[k])), Math.max(...pts.map((p) => p[k]))]);
    };
    const sa = span(a);
    const sb = span(b);
    const slack = 2;
    const lo = [0, 1, 2].map((k) => Math.max(sa[k][0], sb[k][0]));
    const hi = [0, 1, 2].map((k) => Math.min(sa[k][1], sb[k][1]));
    if ([0, 1, 2].some((k) => hi[k] < lo[k] - slack)) return null;
    return { lo, hi: hi.map((v, k) => Math.max(v, lo[k])) };
}

function importedPlan(scene, boxes) {
    const rig = scene.rig;
    if (!rig) return [];
    const worlds = linkMatrices(rig, {});
    const origin = (j) => {
        const m = worlds.get(j.child);
        return m ? [[m[3], m[7], m[11]]] : [];
    };
    const byLink = new Map();
    (boxes || []).forEach((it) => { if (!byLink.has(it.link)) byLink.set(it.link, []); byLink.get(it.link).push(it.box); });
    const plan = [];
    for (const j of rig.joints) {
        const moving = j.type !== 'fixed';
        let at = origin(j);
        let where = 'eklem noktası';
        const patch = !moving && byLink.has(j.parent) && byLink.has(j.child) ? contact(byLink.get(j.parent), byLink.get(j.child)) : null;
        if (patch) {
            // screws at the corners of the contact patch, along the thinnest direction of the overlap
            const size = patch.hi.map((v, k) => v - patch.lo[k]);
            const axis = size.indexOf(Math.min(...size));
            const [u, v] = [0, 1, 2].filter((k) => k !== axis);
            const cx = (patch.lo[u] + patch.hi[u]) / 2;
            const cy = (patch.lo[v] + patch.hi[v]) / 2;
            const hu = Math.max(size[u] / 2 - Math.min(4, size[u] / 4), 0);
            const hv = Math.max(size[v] / 2 - Math.min(4, size[v] / 4), 0);
            at = corners(cx, cy, hu, hv).map(([a, b]) => {
                const point = [0, 0, 0];
                point[u] = a;
                point[v] = b;
                point[axis] = patch.hi[axis];
                return point;
            });
            where = 'temas yüzeyinin köşeleri';
        }
        if (!at.length) continue;
        plan.push({
            step: plan.length + 1,
            part: j.child,
            host: j.parent,
            screw: moving ? 'Servo: 4× M2.5 gövde + 1× mil vidası' : `${at.length}× M3 vida (yapıştırma da olur)`,
            qty: moving ? 5 : at.length,
            at,
            note: moving
                ? `${j.name}: ${j.child} bu eklemde ${j.parent} üzerinde döner; servo gövdesi ${j.parent} tarafına, kol ${j.child} tarafına bağlanır.`
                : `${j.name}: ${j.child}, ${j.parent} ile sabit birleşir; vidalar: ${where} (URDF'de delik bilgisi yoktur, konum öneridir).`,
        });
    }
    return plan;
}
