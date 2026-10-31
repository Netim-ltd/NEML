// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// 3D viewer for a robot model: orbit/zoom/pan, click a part, exploded view and assembly animation.
// The scene is the JSON the lab publishes (brain/neml_brain/evolution/model_scene.py): millimetres,
// +x forward, +y left, +z up. Printed parts are STL files, everything else is a proxy box.
import * as THREE from 'three';
import { STLLoader } from './STLLoader.js';
import { OrbitControls } from './OrbitControls.js';
import { STLExporter } from './STLExporter.js';
import { linkMatrices, partMatrix, movable } from './rig.js';
import { collisions, centreOfMass, stabilityOfPoints, rigidGroups, groupNeighbours } from './analysis.js';
import { decode } from './nmesh.js';
import { fastenerPlan } from './fasteners.js';

let state = null;

const ease = (t) => t * t * (3 - 2 * t);

export function mount(el, scene, token, dotnet) {
    dispose();
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    el.appendChild(renderer.domElement);

    const world = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 5, 20000);
    camera.up.set(0, 0, 1);
    world.add(new THREE.HemisphereLight(0xffffff, 0x333344, 0.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(400, -600, 900);
    world.add(sun);

    const grid = new THREE.GridHelper(1600, 32, 0x556666, 0x2b3434);
    grid.rotation.x = Math.PI / 2; // GridHelper lies in xz; the world is z-up
    world.add(grid);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    const loader = new STLLoader();
    const geometries = new Map();
    const parts = new Map();
    const pickable = [];
    const loadStl = (url) => {
        if (!geometries.has(url)) {
            geometries.set(url, new Promise((resolve, reject) => {
                loader.load(`${url}?access_token=${encodeURIComponent(token)}`, (g) => { g.center(); g.computeVertexNormals(); resolve(g); }, undefined, reject);
            }));
        }
        return geometries.get(url);
    };

    // The compact mesh (.nmesh, brain/neml_brain/evolution/mesh_formats.py): welded vertices on a
    // 16-bit grid and indexed triangles, a fifth of the STL. Flat shading, like the STL path.
    const loadNmesh = (url) => {
        const key = `m:${url}`;
        if (!geometries.has(key)) {
            geometries.set(key, fetch(`${url}?access_token=${encodeURIComponent(token)}`)
                .then((r) => { if (!r.ok) throw new Error(`mesh ${r.status}`); return r.arrayBuffer(); })
                .then((buffer) => {
                    const { positions, indices } = decode(buffer);
                    const g = new THREE.BufferGeometry();
                    g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
                    g.setIndex(new THREE.BufferAttribute(indices, 1));
                    const flat = g.toNonIndexed();
                    flat.center();
                    flat.computeVertexNormals();
                    return flat;
                }));
        }
        return geometries.get(key);
    };

    /** Up to ~300 of the mesh's own vertices (in the centred geometry's frame), for ground contact. */
    const sampleVertices = (geometry) => {
        const position = geometry.getAttribute('position');
        const step = Math.max(1, Math.floor(position.count / 300));
        const out = [];
        for (let i = 0; i < position.count; i += step) out.push([position.getX(i), position.getY(i), position.getZ(i)]);
        return out;
    };

    const build = async (p) => {
        let geometry;
        if (p.geom.type === 'stl') {
            if (!p.geom.url) return;
            if (p.geom.mesh) {
                try { geometry = await loadNmesh(p.geom.mesh); } catch { geometry = await loadStl(p.geom.url); }
            } else {
                geometry = await loadStl(p.geom.url);
            }
        } else if (p.geom.type === 'cylinder') {
            geometry = new THREE.CylinderGeometry(p.geom.radius, p.geom.radius, p.geom.length, 32).rotateX(Math.PI / 2); // URDF axis is z
        } else if (p.geom.type === 'sphere') {
            geometry = new THREE.SphereGeometry(p.geom.radius, 32, 16);
        } else {
            const [x, y, z] = p.geom.size;
            geometry = new THREE.BoxGeometry(x, y, z);
        }
        const material = new THREE.MeshStandardMaterial({
            color: p.color, roughness: 0.55, metalness: 0.15,
            transparent: p.opacity < 1, opacity: p.opacity, depthWrite: p.opacity >= 0.6,
        });
        const mesh = new THREE.Mesh(geometry, material);
        const base = new THREE.Vector3(...p.pos);
        mesh.position.copy(base);
        mesh.rotation.set(...p.rot.map((d) => THREE.MathUtils.degToRad(d)));
        if (p.quat) mesh.quaternion.set(...p.quat); // imported robots: orientation from the URDF
        if (p.geom.scale3) mesh.scale.set(...p.geom.scale3); // per-axis mesh scale -> mm
        else if (p.geom.scale && p.geom.scale !== 1) mesh.scale.setScalar(p.geom.scale); // mesh units -> mm
        mesh.userData.id = p.id;
        world.add(mesh);
        pickable.push(mesh);
        parts.set(p.id, {
            mesh, base, explode: new THREE.Vector3(...p.explode), order: p.order,
            group: p.group, baseOpacity: p.opacity, hidden: false,
            link: p.link || null, local: p.local || null,
            half: (p.geom.size || [0, 0, 0]).map((v) => v / 2), label: p.label,
            samples: sampleVertices(geometry),
        });
    };

    state = {
        renderer, world, camera, controls, parts, el, dotnet, explode: 0, anim: null,
        selected: null, groupHidden: new Set(), dead: false, shellOpacity: 0.18,
        rig: scene.rig || null, pose: {}, genome: scene.genome || '', scene,
    };

    const resize = () => {
        const w = Math.max(el.clientWidth, 200);
        const h = Math.max(el.clientHeight, 200);
        renderer.setSize(w, h, false);
        renderer.domElement.style.width = '100%';
        renderer.domElement.style.height = '100%';
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
    };
    new ResizeObserver(resize).observe(el);
    resize();

    const ray = new THREE.Raycaster();
    renderer.domElement.addEventListener('click', (e) => {
        const r = renderer.domElement.getBoundingClientRect();
        const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
        ray.setFromCamera(ndc, camera);
        const hits = ray.intersectObjects(pickable.filter((m) => m.visible), false);
        const hit = hits.find((h) => !String(h.object.userData.id).startsWith('shell')) || hits[0];
        const id = hit ? hit.object.userData.id : null;
        highlight(id);
        dotnet.invokeMethodAsync('OnPartPicked', id, id ? partSize(id) : []);
    });

    const frame = (now) => {
        if (!state || state.dead) return;
        stepAnimation(now);
        controls.update();
        renderer.render(world, camera);
        requestAnimationFrame(frame);
    };

    requestAnimationFrame(frame); // parts appear as they arrive; the camera is fitted when all are in
    let loaded = 0;
    const total = scene.parts.length;
    const progress = () => { try { dotnet.invokeMethodAsync('OnLoadProgress', loaded, total); } catch { /* disposed */ } };
    return Promise.all(scene.parts.map((part) => build(part).catch(() => null).then(() => {
        loaded += 1;
        if (state && !state.dead && (loaded % 3 === 0 || loaded === total)) progress();
        if (loaded === Math.ceil(total / 3)) { fitCamera(); setShell(state.shellOpacity); }
    }))).then(() => {
        fitCamera();
        applyExplode(0);
        setShell(state.shellOpacity);
        return parts.size;
    });
}

function fitCamera() {
    // frame the real extent of everything visible (not just the part centres), so a small
    // imported robot fills the view instead of floating in the distance
    const box = new THREE.Box3();
    state.parts.forEach((p) => { if (p.mesh.visible !== false) box.expandByObject(p.mesh); });
    if (box.isEmpty()) return;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const fov = THREE.MathUtils.degToRad(state.camera.fov);
    const distance = (sphere.radius / Math.sin(fov / 2)) * 1.15;
    const c = sphere.center;
    state.controls.target.copy(c);
    state.camera.position.set(c.x + distance * 0.62, c.y - distance * 0.72, c.z + distance * 0.42);
    state.camera.near = Math.max(distance / 500, 0.1);
    state.camera.far = distance * 40;
    state.camera.updateProjectionMatrix();
    state.controls.update();
}

/** Pose the imported robot: every part follows its link (rig.js), then the exploded offset is re-applied. */
function applyPose() {
    const { rig, parts } = state;
    if (!rig) return;
    const worlds = linkMatrices(rig, state.pose);
    const m = new THREE.Matrix4();
    const position = new THREE.Vector3();
    const quaternion = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    parts.forEach((part) => {
        if (!part.link || !part.local || !worlds.has(part.link)) return;
        m.set(...partMatrix(worlds.get(part.link), part.local));
        m.decompose(position, quaternion, scale);
        part.base.copy(position);
        part.base.z -= state.zShift || 0;
        part.mesh.quaternion.copy(quaternion);
    });
    applyExplode(state.explode);
}

export function rigJoints() {
    return state && state.rig ? movable(state.rig) : [];
}

export function setJoint(name, value) {
    if (!state || !state.rig) return;
    state.pose[name] = value;
    applyPose();
}

export function setPose(values) {
    if (!state || !state.rig) return;
    state.pose = { ...values };
    applyPose();
}

export function getPose() {
    return state ? { ...state.pose } : {};
}

export function resetPose() {
    if (state) setPose({});
}

export function randomPose() {
    if (!state || !state.rig) return;
    const values = {};
    movable(state.rig).forEach((j) => {
        const span = j.upper - j.lower;
        values[j.name] = j.lower + (0.15 + Math.random() * 0.7) * span;
    });
    setPose(values);
}

function poseStore(model) {
    return `neml.poses.${model}`;
}

/** Saved poses live in this browser only (storage may be blocked: then nothing is saved). */
export function listPoses() {
    try { return JSON.parse(localStorage.getItem(poseStore(state.genome.split('@')[0])) || '{}'); } catch { return {}; }
}

export function savePose(name) {
    if (!state || !name) return false;
    const all = listPoses();
    all[name] = getPose();
    try { localStorage.setItem(poseStore(state.genome.split('@')[0]), JSON.stringify(all)); return true; } catch { return false; }
}

export function loadPose(name) {
    const all = listPoses();
    if (all[name]) setPose(all[name]);
    return !!all[name];
}

export function deletePose(name) {
    const all = listPoses();
    delete all[name];
    try { localStorage.setItem(poseStore(state.genome.split('@')[0]), JSON.stringify(all)); } catch { /* blocked */ }
}

function worldBoxes() {
    const items = [];
    state.parts.forEach((part, id) => {
        if (!part.link) return;
        const q = part.mesh.quaternion;
        items.push({ id, link: part.link, box: { c: [part.base.x, part.base.y, part.base.z], q: [q.x, q.y, q.z, q.w], h: part.half } });
    });
    return items;
}

function setMarker(name, position, color, radius) {
    if (!state.markers) state.markers = {};
    let marker = state.markers[name];
    if (!marker) {
        marker = new THREE.Mesh(new THREE.SphereGeometry(radius, 20, 12), new THREE.MeshBasicMaterial({ color, depthTest: false }));
        marker.renderOrder = 10;
        state.world.add(marker);
        state.markers[name] = marker;
    }
    marker.visible = !!position;
    if (position) marker.position.set(...position);
}

/**
 * What the current pose means: parts that run into each other (and which are shown in red), the
 * centre of mass from the URDF's link masses (or the boxes' volumes when there are none) and
 * whether it stands. Returns plain data for the panel.
 */
export function analyze(showCom = true) {
    if (!state || !state.rig) return null;
    const items = worldBoxes();
    const groups = rigidGroups(state.rig);
    items.forEach((it) => { it.link = groups.get(it.link) || it.link; }); // parts of a rigid body share a group
    const hits = collisions(items, groupNeighbours(state.rig, groups));
    const hitIds = new Set(hits.flat());
    state.parts.forEach((part, id) => {
        if (id === state.selected) return;
        part.mesh.material.emissive.setHex(hitIds.has(id) ? 0x7a1a1a : 0x000000);
    });
    const worlds = linkMatrices(state.rig, state.pose);
    const points = [];
    const masses = state.rig.links || {};
    Object.entries(masses).forEach(([name, info]) => {
        const m = worlds.get(name);
        if (!m) return;
        const [x, y, z] = info.com;
        points.push({ m: info.mass, p: [m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7], m[8] * x + m[9] * y + m[10] * z + m[11]] });
    });
    const estimated = points.length === 0;
    if (estimated) {
        items.forEach((it) => points.push({ m: it.box.h[0] * it.box.h[1] * it.box.h[2], p: [...it.box.c] }));
    }
    const com = centreOfMass(points);
    const zShift = state.zShift || 0;
    const world = new THREE.Matrix4();
    const vector = new THREE.Vector3();
    const surface = [];
    state.parts.forEach((part) => {
        if (!part.link || !part.samples) return;
        world.compose(part.base, part.mesh.quaternion, part.mesh.scale);
        part.samples.forEach(([x, y, z]) => { vector.set(x, y, z).applyMatrix4(world); surface.push([vector.x, vector.y, vector.z]); });
    });
    const stand = com ? stabilityOfPoints(surface, com.p) : null;
    setMarker('com', showCom && com ? com.p : null, 0xff3b30, 12);
    const label = (id) => (state.parts.get(id) || {}).label || id;
    return {
        collisions: hits.map(([a, b]) => [label(a), label(b)]),
        collisionIds: hits,
        mass: com ? com.mass : 0,
        massEstimated: estimated,
        com: com ? com.p.map((v) => Math.round(v * 10) / 10) : null,
        stable: stand ? stand.stable : null,
        margin: stand ? Math.round(stand.margin * 10) / 10 : null,
        height: stand ? Math.round(stand.height * 10) / 10 : null,
        ground: stand ? Math.round(stand.ground * 10) / 10 : null,
        zShift,
    };
}

/** Lower the robot so its lowest point touches the ground plane (z = 0). */
export function dropToGround() {
    if (!state || !state.rig) return null;
    const result = analyze();
    if (!result || result.ground === null) return result;
    state.zShift = (state.zShift || 0) + result.ground;
    state.parts.forEach((part) => { part.base.z -= result.ground; });
    applyExplode(state.explode);
    return analyze();
}

/** The screw plan; imported robots get their screws from where the parts touch now (boxes without the ground shift). */
function currentPlan() {
    const shift = state.zShift || 0;
    const boxes = state.rig ? worldBoxes().map((it) => ({ ...it, box: { ...it.box, c: [it.box.c[0], it.box.c[1], it.box.c[2] + shift] } })) : null;
    return fastenerPlan(state.scene, boxes);
}

/** The screw plan of the scene (see fasteners.js). */
export function fasteners() {
    return state ? currentPlan() : [];
}

/** Mark where the screws of plan step `step` go (null clears) and select the part they hold. */
export function showFastener(step) {
    if (!state) return;
    (state.screwMarks || []).forEach((m) => { state.world.remove(m); m.geometry.dispose(); m.material.dispose(); });
    state.screwMarks = [];
    const item = step ? currentPlan().find((f) => f.step === step) : null;
    if (!item) return;
    const zShift = state.zShift || 0;
    item.at.forEach(([x, y, z]) => {
        const m = new THREE.Mesh(new THREE.SphereGeometry(2.6, 16, 10), new THREE.MeshBasicMaterial({ color: 0xff9500, depthTest: false }));
        m.renderOrder = 11;
        m.position.set(x, y, z - zShift);
        state.world.add(m);
        state.screwMarks.push(m);
    });
    const id = [...state.parts.entries()].find(([k, v]) => k === item.part || v.link === item.part);
    if (id) highlight(id[0]);
}

/** Draw cables between parts: `rows` are scene.wiring rows (null clears). */
export function showWires(rows) {
    if (!state) return;
    (state.wireLines || []).forEach((l) => { state.world.remove(l); l.geometry.dispose(); l.material.dispose(); });
    state.wireLines = [];
    (rows || []).forEach((r, i) => {
        const a = state.parts.get(r.a);
        const b = state.parts.get(r.b);
        if (!a || !b) return;
        const color = new THREE.Color().setHSL((i * 0.17) % 1, 0.9, 0.55);
        const mid = a.mesh.position.clone().add(b.mesh.position).multiplyScalar(0.5);
        mid.z += 25 + 6 * (i % 4); // arch over the parts so cables do not hide inside them
        const curve = new THREE.QuadraticBezierCurve3(a.mesh.position.clone(), mid, b.mesh.position.clone());
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(24)), new THREE.LineBasicMaterial({ color, depthTest: false }));
        line.renderOrder = 12;
        state.world.add(line);
        state.wireLines.push(line);
    });
}

export function clearAnalysis() {
    if (!state) return;
    state.parts.forEach((part, id) => { if (id !== state.selected) part.mesh.material.emissive.setHex(0x000000); });
    setMarker('com', null, 0xff3b30, 12);
}

function applyExplode(amount) {
    state.explode = amount;
    state.parts.forEach((p) => p.mesh.position.copy(p.base).addScaledVector(p.explode, amount * 2.2));
}

function stepAnimation(now) {
    const a = state.anim;
    if (!a) return;
    const t = (now - a.start) / 1000;
    if (a.kind === 'wiggle' && state.rig) {
        const values = {};
        movable(state.rig).forEach((j, i) => {
            const mid = (j.lower + j.upper) / 2;
            const amp = (j.upper - j.lower) * 0.3;
            values[j.name] = mid + amp * Math.sin(t * 1.6 + i * 0.8);
        });
        state.pose = values;
        applyPose();
    } else if (a.kind === 'explode') {
        const phase = (t % 8) / 8; // out for 4 s, back for 4 s
        applyExplode(ease(phase < 0.5 ? phase * 2 : (1 - phase) * 2));
    } else if (a.kind === 'assembly') {
        if (!a.steps) a.steps = assemblyTimeline();
        a.steps.forEach((step) => {
            const local = Math.min(Math.max((t - step.start) / FLY, 0), 1);
            step.part.mesh.visible = local > 0 && !state.groupHidden.has(step.part.group);
            step.part.mesh.position.copy(step.part.base).addScaledVector(step.part.explode, 2.2 * (1 - ease(local)));
            step.screws.forEach((m, i) => {
                const k = Math.min(Math.max((t - step.start - FLY - i * SCREW) / SCREW, 0), 1);
                m.visible = k > 0;
                m.position.z = m.userData.z + 26 * (1 - ease(k));
            });
        });
        if (t > a.steps.total) {
            state.anim = null;
            clearScrews();
            applyExplode(0);
            refreshVisibility();
        }
    }
}

const FLY = 0.7;
const SCREW = 0.3;

/** Seating order: the main body first, then what sits on it, closed by the upper shell. */
function assemblyRank(id, part, depth) {
    const fixed = { shell_lower: 0, shell: 0, battery_tray: 1, battery: 2, board_plate: 3, compute: 4, shell_upper: 99 };
    if (id in fixed) return fixed[id];
    if (id.startsWith('bracket_')) return 7;
    if (part.group === 'aktuator') return 8;
    if (part.group === 'bacak') return 9;
    if (part.group === 'ayak') return 10;
    if (part.group === 'sensor') return 6;
    if (part.link && depth.has(part.link)) return 20 + depth.get(part.link); // imported: root link first, then outwards
    return 5;
}

/** One part at a time is set on the main part, then its screws go in; returns the steps with their start times. */
function assemblyTimeline() {
    const depth = new Map();
    if (state.rig) {
        depth.set(state.rig.root, 0);
        for (let changed = true; changed;) {
            changed = false;
            state.rig.joints.forEach((j) => {
                if (depth.has(j.parent) && !depth.has(j.child)) { depth.set(j.child, depth.get(j.parent) + 1); changed = true; }
            });
        }
    }
    const plan = currentPlan();
    const used = new Set();
    const entries = [...state.parts.entries()].map(([id, part]) => ({ id, part, rank: assemblyRank(id, part, depth) }));
    entries.sort((a, b) => a.rank - b.rank || a.part.order - b.part.order);
    let t = 0;
    const steps = entries.map(({ id, part }) => {
        const own = plan.filter((f) => (f.part === id || (part.link && f.part === part.link)) && !used.has(f.step));
        own.forEach((f) => used.add(f.step));
        const screws = own.flatMap((f) => f.at).map(([x, y, z]) => screwMesh([x, y, z - (state.zShift || 0)]));
        const step = { part, start: t, screws };
        t += FLY + screws.length * SCREW + 0.1;
        return step;
    });
    steps.total = t + 1;
    return steps;
}

function screwMesh(at) {
    const m = new THREE.Mesh(
        new THREE.CylinderGeometry(1.7, 1.7, 8, 12),
        new THREE.MeshStandardMaterial({ color: 0xc8c8d0, metalness: 0.8, roughness: 0.3 }),
    );
    m.rotation.x = Math.PI / 2; // along z
    m.position.set(at[0], at[1], at[2]);
    m.userData.z = at[2];
    m.visible = false;
    state.world.add(m);
    (state.screws = state.screws || []).push(m);
    return m;
}

function clearScrews() {
    (state.screws || []).forEach((m) => { state.world.remove(m); m.geometry.dispose(); m.material.dispose(); });
    state.screws = [];
}

function refreshVisibility() {
    state.parts.forEach((p) => { p.mesh.visible = !state.groupHidden.has(p.group); });
}

export function setExplode(amount) {
    if (!state) return;
    clearScrews();
    state.anim = null;
    refreshVisibility();
    applyExplode(amount);
}

export function play(kind) {
    if (!state) return;
    clearScrews();
    state.anim = kind ? { kind, start: performance.now() } : null;
    if (!kind) { refreshVisibility(); applyExplode(0); }
}

export function setShell(opacity) {
    if (!state) return;
    state.shellOpacity = opacity;
    state.parts.forEach((part, id) => {
        if (id !== 'shell' && !id.startsWith('shell_')) return;
        part.mesh.material.opacity = opacity;
        part.mesh.material.transparent = opacity < 1;
        part.mesh.material.depthWrite = opacity >= 0.6;
        part.mesh.visible = opacity > 0.01 && !state.groupHidden.has('govde');
    });
}

export function setGroupVisible(group, visible) {
    if (!state) return;
    if (visible) state.groupHidden.delete(group); else state.groupHidden.add(group);
    refreshVisibility();
    setShell(state.shellOpacity);
}

export function highlight(id) {
    if (!state) return;
    if (state.selected && state.parts.has(state.selected)) {
        state.parts.get(state.selected).mesh.material.emissive.setHex(0x000000);
    }
    state.selected = id;
    if (id && state.parts.has(id)) {
        state.parts.get(id).mesh.material.emissive.setHex(0x2a5a55);
    }
}

export function dispose() {
    if (!state) return;
    state.dead = true;
    state.renderer.dispose();
    state.renderer.domElement.remove();
    state = null;
}

function partSize(id) {
    const part = state.parts.get(id);
    if (!part) return [];
    const box = new THREE.Box3().setFromObject(part.mesh);
    const size = box.getSize(new THREE.Vector3());
    return [size.x, size.y, size.z].map((v) => Math.round(v * 10) / 10);
}

/** Show only one part (centred, zoomed) so it can be looked at on its own. */
export function isolate(id) {
    if (!state || !state.parts.has(id)) return;
    state.anim = null;
    state.parts.forEach((p, key) => { p.mesh.visible = key === id; p.mesh.position.copy(p.base); });
    const mesh = state.parts.get(id).mesh;
    const box = new THREE.Box3().setFromObject(mesh);
    const centre = box.getCenter(new THREE.Vector3());
    const radius = Math.max(...box.getSize(new THREE.Vector3()).toArray()) * 1.8 + 40;
    state.controls.target.copy(centre);
    state.camera.position.set(centre.x + radius * 0.8, centre.y - radius, centre.z + radius * 0.5);
    state.controls.update();
}

export function showAll() {
    if (!state) return;
    refreshVisibility();
    applyExplode(0);
    setShell(state.shellOpacity);
    fitCamera();
}

export function setWireframe(on) {
    if (!state) return;
    state.parts.forEach((p) => { p.mesh.material.wireframe = on; });
}

function download(name, blob) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** The whole assembled model as one binary STL (millimetres), the visible parts only. */
export function exportStl(name) {
    if (!state) return;
    const group = new THREE.Group();
    state.parts.forEach((p) => {
        if (!p.mesh.visible || p.group === 'govde') return; // the shell is a placeholder, not a part
        const copy = new THREE.Mesh(p.mesh.geometry, p.mesh.material);
        copy.position.copy(p.base);
        copy.rotation.copy(p.mesh.rotation);
        group.add(copy);
    });
    group.updateMatrixWorld(true);
    const data = new STLExporter().parse(group, { binary: true });
    download(name, new Blob([data], { type: 'model/stl' }));
}

export function downloadText(name, text, mime) {
    download(name, new Blob([text], { type: mime }));
}
