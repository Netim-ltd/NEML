# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy. All rights reserved.
# Proprietary and confidential. Unauthorized use is prohibited.
"""Linear-elastic static finite elements on a real tetrahedral mesh: gmsh meshes the part's STEP (second-order tets), the stiffness is
assembled here with 10-node tetrahedra and solved with scipy. Result: displacement, von Mises stress and the safety factor against the
material's yield. # ponytail: small strains and one load case; stress is read at the Gauss points, so sharp supports (re-entrant corners,
a fixed face edge) show stress peaks that are mesh artefacts, not real; loads are on one flat face, supports on another."""

from __future__ import annotations

from typing import Any

# E (MPa), Poisson ratio, yield (MPa); printed plastics lose half to layer anisotropy
MATERIAL = {
    "PLA": (3500.0, 0.36, 50.0, 0.5),
    "PETG": (2100.0, 0.40, 45.0, 0.5),
    "ASA": (2000.0, 0.39, 38.0, 0.5),
    "PA6-CF": (5000.0, 0.35, 70.0, 0.5),
    "ALU": (70000.0, 0.33, 240.0, 1.0),
    "STEEL": (210000.0, 0.30, 250.0, 1.0),
}
_A, _B = 0.1381966011250105, 0.5854101966249685
GAUSS = ((_A, _A, _A), (_B, _A, _A), (_A, _B, _A), (_A, _A, _B))  # four points, exact for the quadratic integrands; weight 1/24 each
W = 1 / 24


def shape_derivs(xi: float, eta: float, zeta: float) -> Any:
    """d N / d(xi, eta, zeta) of the 10-node tetrahedron (gmsh node order: 4 vertices, then edges 01 12 20 30 32 31)."""
    import numpy as np

    lam = [1 - xi - eta - zeta, xi, eta, zeta]
    dl = [(-1, -1, -1), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    out = [[(4 * lam[i] - 1) * dl[i][k] for k in range(3)] for i in range(4)]
    for i, j in ((0, 1), (1, 2), (2, 0), (3, 0), (3, 2), (3, 1)):
        out.append([4 * (lam[j] * dl[i][k] + lam[i] * dl[j][k]) for k in range(3)])
    return np.array(out)


def elasticity(e: float, nu: float) -> Any:
    import numpy as np

    c = e / ((1 + nu) * (1 - 2 * nu))
    d = np.zeros((6, 6))
    d[:3, :3] = c * nu
    for i in range(3):
        d[i, i] = c * (1 - nu)
        d[3 + i, 3 + i] = c * (1 - 2 * nu) / 2
    return d


def b_matrix(dn: Any) -> Any:
    """Strain-displacement matrix (6 x 30) from d N / d(x, y, z) (10 x 3)."""
    import numpy as np

    b = np.zeros((6, 30))
    for n in range(10):
        dx, dy, dz = dn[n]
        b[0, 3 * n], b[1, 3 * n + 1], b[2, 3 * n + 2] = dx, dy, dz
        b[3, 3 * n], b[3, 3 * n + 1] = dy, dx
        b[4, 3 * n + 1], b[4, 3 * n + 2] = dz, dy
        b[5, 3 * n], b[5, 3 * n + 2] = dz, dx
    return b


def gradients(dn: Any, x: Any) -> tuple[Any, float]:
    """d N / d(x, y, z) (10 x 3) and the Jacobian determinant for an element with corner coordinates x (10 x 3)."""
    import numpy as np

    jac = dn.T @ x  # jac[i, j] = d x_j / d xi_i
    return dn @ np.linalg.inv(jac).T, float(np.linalg.det(jac))


def von_mises(s: Any) -> float:
    sxx, syy, szz, sxy, syz, sxz = s
    return float((0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy**2 + syz**2 + sxz**2)) ** 0.5)


def parse_msh(path: str) -> tuple[Any, Any, Any]:
    """Nodes (n x 3), 10-node tets (m x 10, zero-based) and 6-node surface triangles (k x 6) of a gmsh 2 ASCII mesh."""
    import numpy as np

    lines = open(path, encoding="utf-8").read().split("\n")
    i = lines.index("$Nodes") + 1
    n = int(lines[i])
    nodes = np.zeros((n, 3))
    ids: dict[int, int] = {}
    for k in range(n):
        p = lines[i + 1 + k].split()
        ids[int(p[0])] = k
        nodes[k] = [float(v) for v in p[1:4]]
    j = lines.index("$Elements") + 1
    tets, tris = [], []
    for k in range(int(lines[j])):
        p = lines[j + 1 + k].split()
        kind, ntags = int(p[1]), int(p[2])
        conn = [ids[int(v)] for v in p[3 + ntags :]]
        if kind == 11:
            tets.append(conn)
        elif kind == 9:
            tris.append(conn)
    return nodes, np.array(tets, dtype=int), np.array(tris, dtype=int).reshape(-1, 6)


def solve(nodes: Any, tets: Any, tris: Any, material: str, fixed: str, load: dict[str, Any]) -> dict[str, Any]:
    """Static solve: nodes on the `fixed` side ('x-', 'z+', ...) of the bounding box are clamped, `load` {face, force [fx, fy, fz] N} is spread over that side's surface."""
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl

    e, nu, yield_mpa, aniso = MATERIAL[material]
    d = elasticity(e, nu)
    lo, hi = nodes.min(axis=0), nodes.max(axis=0)
    tol = 1e-6 * float((hi - lo).max()) + 1e-6

    def on(side: str) -> Any:
        ax, sgn = "xyz".index(side[0]), side[1]
        return np.abs(nodes[:, ax] - (hi[ax] if sgn == "+" else lo[ax])) < tol

    fixed_nodes = np.where(on(fixed))[0]
    if not len(fixed_nodes):
        raise ValueError(f"no nodes on the fixed side {fixed!r}")
    ndof = 3 * len(nodes)
    dns = [shape_derivs(*g) for g in GAUSS]
    rows, cols, vals = [], [], []
    dofs = (3 * tets[:, :, None] + np.arange(3)).reshape(len(tets), 30)
    for el in range(len(tets)):
        x = nodes[tets[el]]
        ke = np.zeros((30, 30))
        for dn in dns:
            grad, det = gradients(dn, x)
            if det <= 0:
                raise ValueError("a mesh element is inverted")
            b = b_matrix(grad)
            ke += b.T @ d @ b * det * W
        rows.append(np.repeat(dofs[el], 30))
        cols.append(np.tile(dofs[el], 30))
        vals.append(ke.ravel())
    k = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(ndof, ndof)).tocsr()

    f = np.zeros(ndof)
    face = on(load["face"])
    force = np.array(load["force"], dtype=float)
    area_total = 0.0
    weights = np.zeros(len(nodes))
    for tri in tris:
        if face[tri].all():
            p = nodes[tri[:3]]
            a = 0.5 * np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0]))
            area_total += a
            weights[tri[3:]] += a / 3  # consistent loads of a quadratic triangle: corners 0, mid-edges a/3
    if area_total <= 0:
        raise ValueError(f"no surface on the load side {load['face']!r}")
    for n in np.where(weights > 0)[0]:
        f[3 * n : 3 * n + 3] += force * weights[n] / area_total
    clamped = (3 * fixed_nodes[:, None] + np.arange(3)).ravel()
    free = np.setdiff1d(np.arange(ndof), clamped)
    u = np.zeros(ndof)
    u[free] = spl.spsolve(k[free][:, free].tocsc(), f[free])

    peak = 0.0
    for el in range(len(tets)):
        x, ue = nodes[tets[el]], u[dofs[el]]
        for dn in dns:
            b = b_matrix(gradients(dn, x)[0])
            peak = max(peak, von_mises(d @ b @ ue))
    disp = np.linalg.norm(u.reshape(-1, 3), axis=1)
    allowed = yield_mpa * aniso
    return {
        "material": material,
        "nodes": len(nodes),
        "elements": len(tets),
        "max_displacement_mm": round(float(disp.max()), 5),
        "max_von_mises_mpa": round(peak, 3),
        "allowable_mpa": allowed,
        "safety_factor": round(allowed / peak, 3) if peak > 0 else None,
        "reaction_n": [round(float(v), 4) for v in force],
    }
