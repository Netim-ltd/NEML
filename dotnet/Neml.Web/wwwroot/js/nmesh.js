// Copyright (c) 2026 Mustafa Gulsoy.
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The viewer's compact mesh format (.nmesh), written by brain/neml_brain/evolution/mesh_formats.py
// `compact`: "NM1\0", vertex count, index count, box min (3 float32), box max (3 float32), then
// uint16 x y z per vertex on a 16-bit grid inside the box, then the triangle indices (uint16, or
// uint32 above 65535 vertices). Pure decoding, no THREE; tests compare it with the Python side.

export function decode(buffer) {
    const view = new DataView(buffer);
    if (String.fromCharCode(...new Uint8Array(buffer, 0, 3)) !== 'NM1') throw new Error('not a mesh');
    const vertexCount = view.getUint32(4, true);
    const indexCount = view.getUint32(8, true);
    const lo = [0, 1, 2].map((k) => view.getFloat32(12 + 4 * k, true));
    const hi = [0, 1, 2].map((k) => view.getFloat32(24 + 4 * k, true));
    const grid = new Uint16Array(buffer.slice(36, 36 + vertexCount * 6));
    const raw = buffer.slice(36 + vertexCount * 6);
    const indices = vertexCount >= 65536 ? new Uint32Array(raw, 0, indexCount) : new Uint16Array(raw, 0, indexCount);
    const positions = new Float32Array(vertexCount * 3);
    for (let i = 0; i < vertexCount; i++) {
        for (let k = 0; k < 3; k++) {
            const span = hi[k] > lo[k] ? hi[k] - lo[k] : 1;
            positions[i * 3 + k] = lo[k] + (grid[i * 3 + k] / 65535) * span;
        }
    }
    return { positions, indices };
}
