# ruff: noqa: E501
# Copyright (c) 2026 Mustafa Gulsoy. All rights reserved.
# Proprietary and confidential. Unauthorized use is prohibited.
"""A manufacturing drawing from the line work of three orthographic views (third-angle projection, ISO 5456/128 style):
standard scale, sheet size by fit (A4 -> A2), visible and hidden lines, overall dimensions with an optional tolerance, hole callouts,
an optional section view with hatching, and a title block. Output is SVG (to read) and DXF (to open in any CAD). Pure Python."""

from __future__ import annotations

import math
from datetime import date
from html import escape
from typing import Any

SHEETS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0)}
SCALES = (10.0, 5.0, 2.0, 1.0, 0.5, 0.2, 0.1, 0.05)  # ISO 5455 preferred scales
MARGIN, GAP, BLOCK = 10.0, 26.0, 38.0
PAD_L, PAD_R, PAD_T, PAD_B = 24.0, 14.0, 12.0, 20.0

Line = list[list[float]]
_ASCII = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "Ç": "C", "Ğ": "G", "İ": "I", "Ö": "O", "Ş": "S", "Ü": "U", "Ø": "%%c", "°": "%%d", "±": "%%p", "⌴": "cbore "})


def fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def scale_label(s: float) -> str:
    return f"{fmt(s)}:1" if s >= 1 else f"1:{fmt(1 / s)}"


def extent(lines: list[Line]) -> tuple[float, float, float, float]:
    xs = [p[0] for ln in lines for p in ln]
    ys = [p[1] for ln in lines for p in ln]
    return (min(xs), max(xs), min(ys), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)


def fit_sheet(c1: float, c2: float, r1: float, r2: float, want: float | None = None) -> tuple[str, float]:
    """Smallest sheet, largest standard scale (or the wanted one) that holds the view grid."""
    for name, (w, h) in SHEETS.items():
        for s in ([want] if want else SCALES):
            if PAD_L + (c1 + c2) * s + GAP + PAD_R <= w - 2 * MARGIN and PAD_T + (r1 + r2) * s + GAP + PAD_B <= h - 2 * MARGIN - BLOCK:
                return name, s
    return "A2", SCALES[-1]


class _Out:
    """SVG and DXF built from the same calls, in sheet millimetres with y up for DXF and y down for SVG."""

    def __init__(self, w: float, h: float) -> None:
        self.w, self.h = w, h
        self.svg: list[str] = []
        self.dxf: list[str] = []

    def poly(self, pts: list[tuple[float, float]], layer: str) -> None:
        if len(pts) < 2:
            return
        hidden = layer == "HIDDEN"
        d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts)
        self.svg.append(f'<path d="{d}" class="{"h" if hidden else "v"}"/>')
        for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
            self.line(x1, y1, x2, y2, layer, svg=False)

    def line(self, x1: float, y1: float, x2: float, y2: float, layer: str, svg: bool = True, cls: str = "t") -> None:
        if svg:
            self.svg.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" class="{cls}"/>')
        self.dxf.append(f"0\nLINE\n8\n{layer}\n10\n{x1:.3f}\n20\n{self.h - y1:.3f}\n30\n0\n11\n{x2:.3f}\n21\n{self.h - y2:.3f}\n31\n0\n")

    def text(self, x: float, y: float, s: str, size: float = 3.5, anchor: str = "middle", rotate: bool = False, bold: bool = False) -> None:
        rot = f' transform="rotate(-90 {x:.2f} {y:.2f})"' if rotate else ""
        weight = ' font-weight="700"' if bold else ""
        self.svg.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}"{rot}{weight}>{escape(s)}</text>')
        self.dxf.append(f"0\nTEXT\n8\nDIM\n10\n{x:.3f}\n20\n{self.h - y:.3f}\n30\n0\n40\n{size}\n1\n{s.translate(_ASCII)}\n50\n{90 if rotate else 0}\n")

    def rect(self, x: float, y: float, w: float, h: float, layer: str = "FRAME", width: float = 0.5) -> None:
        self.svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="none" stroke="#000" stroke-width="{width}"/>')
        for a, b in (((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y))):
            self.line(a[0], a[1], b[0], b[1], layer, svg=False)


def _dim_h(o: _Out, x1: float, x2: float, y_obj: float, y_dim: float, text: str) -> None:
    for x in (x1, x2):
        o.line(x, y_obj + 1.5, x, y_dim + 2, "DIM")
    o.line(x1, y_dim, x2, y_dim, "DIM", cls="d")
    o.text((x1 + x2) / 2, y_dim - 1.3, text)


def _dim_v(o: _Out, y1: float, y2: float, x_obj: float, x_dim: float, text: str) -> None:
    for y in (y1, y2):
        o.line(x_obj - 1.5, y, x_dim - 2, y, "DIM")
    o.line(x_dim, y1, x_dim, y2, "DIM", cls="d")
    o.text(x_dim - 1.3, (y1 + y2) / 2, text, rotate=True)


def _frame(o: _Out, x: float, y: float, cells: list[str]) -> None:
    """A feature control frame (ISO 1101): a symbol cell for position, then the tolerance and datum cells. (x, y) = its left, vertical middle."""
    h, cx = 5.0, x
    widths = [h] + [max(7.0, 2.6 * len(c) + 3) for c in cells]
    o.rect(x, y - h / 2, sum(widths), h, "DIM", 0.25)
    pts = [(x + h / 2 + 1.6 * math.cos(a * math.pi / 6), y + 1.6 * math.sin(a * math.pi / 6)) for a in range(13)]
    o.poly(pts, "DIM")  # position symbol: a circle with a cross
    o.line(x + h / 2 - 2.6, y, x + h / 2 + 2.6, y, "DIM")
    o.line(x + h / 2, y - 2.6, x + h / 2, y + 2.6, "DIM")
    cx += widths[0]
    for c, w in zip(cells, widths[1:], strict=False):
        o.line(cx, y - h / 2, cx, y + h / 2, "DIM")
        o.text(cx + w / 2, y + 1.2, c, 3.0)
        cx += w


def _roughness(o: _Out, x: float, y: float, ra: str) -> None:
    """The general surface-roughness symbol (ISO 1302, machined surface) with its Ra value; (x, y) = the tip."""
    o.poly([(x - 3.5, y - 5.5), (x, y), (x + 7, y - 11)], "DIM")
    o.line(x + 7, y - 11, x + 16, y - 11, "DIM")
    o.text(x + 8, y - 12.4, f"Ra {ra}", 3.0, anchor="start")


def _holes(o: _Out, holes: list[dict[str, Any]], s: float, views: dict[str, tuple], cap: int = 6) -> None:
    """Position dimensions of the holes, measured from the part's edges (ordinate style); one per distinct coordinate."""
    done: set[tuple[str, int, float]] = set()
    for h in holes[:cap]:
        x, y, z = h["at"]
        ax = h["axis"]
        view, (u, v) = ("top", (x, y)) if ax == "z" else ("front", (x, z)) if ax == "y" else ("right", (y, z))
        left, b, e = views[view]  # view left, bottom (sheet), extent (umin, umax, vmin, vmax)
        cx, cy = left + (u - e[0]) * s, b - (v - e[2]) * s
        if (view, 0, round(u, 2)) not in done:
            done.add((view, 0, round(u, 2)))
            if abs(u - e[0]) > 0.01:
                _dim_h(o, left, cx, b, b + (22 if view == "front" else 12), fmt(u - e[0]))
        if (view, 1, round(v, 2)) not in done:
            done.add((view, 1, round(v, 2)))
            if abs(v - e[2]) > 0.01:
                _dim_v(o, cy, b, left, left - (20 if view != "right" else 10), fmt(v - e[2]))


def _callout(h: dict[str, Any]) -> str:
    d = h["d"]
    kind = h.get("kind", "plain")
    if kind == "tap":
        return f"M{fmt(d)}" + (f" x {fmt(h['depth'])}" if h.get("depth") else "") + " (kılavuz)"
    base = f"Ø{fmt(d)}" + (" geçme" if not h.get("depth") else f" x {fmt(h['depth'])}")
    if kind == "cbore":
        return f"{base}  ⌴Ø{fmt(h['d2'])} x {fmt(h['depth2'])}"
    if kind == "csink":
        return f"{base}  havşa Ø{fmt(h['d2'])} 90°"
    return base


def compose(views: dict[str, Any], bbox: list[float], meta: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """views: {"front"|"top"|"right"|"section": {"visible": [polyline], "hidden": [polyline], "hatch": [ring]}}; bbox [xmin, ymin, zmin, xmax, ymax, zmax].
    meta: title, material, mass_g, tolerances {"x"|"y"|"z": "±0.1"}, holes [{at, axis, d, kind, ...}], notes [str], scale (optional)."""
    ext = {k: extent(v["visible"] or v["hidden"]) for k, v in views.items()}
    size = {k: (e[1] - e[0], e[3] - e[2]) for k, e in ext.items()}
    sec = "section" in views
    c1 = max(size["front"][0], size["top"][0])
    c2 = max(size["right"][0], size["section"][0] if sec else 0.0)
    r1 = max(size["top"][1], size["section"][1] if sec else 0.0)
    r2 = max(size["front"][1], size["right"][1])
    sheet, s = fit_sheet(c1, c2, r1, r2, meta.get("scale"))
    sw, sh = SHEETS[sheet]
    o = _Out(sw, sh)
    # top-left of the grid; rows grow downwards in the drawing
    gx = MARGIN + PAD_L
    gy = MARGIN + PAD_T
    row1_h, row2_h = r1 * s, r2 * s
    y_row2_bottom = gy + row1_h + GAP + row2_h
    x_col2 = gx + c1 * s + GAP

    def place(name: str, left: float, bottom: float, ox: float, oy: float) -> None:
        """Draw a view with its view-coordinate point (ox, oy) at the sheet point (left, bottom)."""
        px = lambda u: left + (u - ox) * s  # noqa: E731
        py = lambda v: bottom - (v - oy) * s  # noqa: E731
        for ln in views[name]["hidden"]:
            o.poly([(px(p[0]), py(p[1])) for p in ln], "HIDDEN")
        for ln in views[name]["visible"]:
            o.poly([(px(p[0]), py(p[1])) for p in ln], "VISIBLE")
        for ring in views[name].get("hatch", []):
            o.svg.append('<path d="M' + " L".join(f"{px(p[0]):.2f} {py(p[1]):.2f}" for p in ring) + ' Z" fill="url(#hatch)" fill-rule="evenodd" stroke="none"/>')

    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    # front: u = x, v = z; top: u = x, v = y (above the front); right: u = y, v = z (to the right of the front)
    fl, fb = gx, y_row2_bottom
    fe = ext["front"]
    place("front", fl, fb, fe[0], fe[2])
    te = ext["top"]
    tb = gy + row1_h
    place("top", fl + (te[0] - fe[0]) * s, tb, te[0], te[2])
    re_ = ext["right"]
    rl = x_col2
    place("right", rl, fb, re_[0], re_[2])
    if sec:
        se = ext["section"]
        place("section", x_col2, tb, se[0], se[2])
        o.text(x_col2 + size["section"][0] * s / 2, tb - size["section"][1] * s - 3, f"KESİT {meta.get('section_label', 'A-A')}", 3.5, bold=True)

    tol = meta.get("tolerances") or {}

    def dtext(v: float, axis: str) -> str:
        return f"{fmt(v)} {tol[axis]}" if tol.get(axis) else fmt(v)

    fx0, fx1 = fl, fl + size["front"][0] * s
    # overall width under the front, overall height left of the front, depth left of the top view
    _dim_h(o, fx0, fx1, fb, fb + 12, dtext(xmax - xmin, "x"))
    _dim_v(o, fb - size["front"][1] * s, fb, fx0, fx0 - 10, dtext(zmax - zmin, "z"))
    tx0 = fl + (te[0] - fe[0]) * s
    _dim_v(o, tb - size["top"][1] * s, tb, tx0, tx0 - 10, dtext(ymax - ymin, "y"))

    # hole callouts on the view that looks along the hole
    for i, h in enumerate(meta.get("holes") or []):
        x, y, z = h["at"]
        if h["axis"] == "z":
            cx, cy = tx0 + (x - te[0]) * s, tb - (y - te[2]) * s
        elif h["axis"] == "y":
            cx, cy = fl + (x - fe[0]) * s, fb - (z - fe[2]) * s
        else:
            cx, cy = rl + (y - re_[0]) * s, fb - (z - re_[2]) * s
        r = (h["d"] / 2) * s
        ex, ey = cx + max(r, 3) * 0.7071, cy - max(r, 3) * 0.7071
        tx, ty = ex + 8 + 4 * (i % 3), ey - 8 - 5 * (i % 2)
        o.line(ex, ey, tx, ty, "DIM")
        o.line(tx, ty, tx + 3, ty, "DIM")
        o.text(tx + 4, ty + 1.2, _callout(h), 3.2, anchor="start")

    if meta.get("holes"):
        _holes(o, meta["holes"], s, {"top": (tx0, tb, te), "front": (fl, fb, fe), "right": (rl, fb, re_)})
    if meta.get("gdt"):  # position tolerance of the holes against datum A (the front view's right edge); the tolerance is the lab's choice, 0.2 mm by default
        ay = fb - size["front"][1] * s / 2
        o.poly([(fx1 + 6, ay + 3), (fx1 + 6, ay - 3), (fx1, ay)], "DIM")
        o.line(fx1 + 6, ay, fx1 + 10, ay, "DIM")
        o.rect(fx1 + 10, ay - 2.5, 5, 5, "DIM", 0.25)
        o.text(fx1 + 12.5, ay + 1.2, "A", 3.0)
        for i, h in enumerate((meta.get("holes") or [])[:3]):
            _frame(o, sw - MARGIN - 60, MARGIN + 10 + 8 * i, [f"Ø{fmt(h.get('pos_tol', 0.2))}", "A"])
    ra = meta.get("ra") or ("12.5" if meta.get("process") == "print" else "3.2")
    _roughness(o, sw - MARGIN - 34, sh - MARGIN - BLOCK - 6, ra)

    # frame and title block
    o.rect(MARGIN, MARGIN, sw - 2 * MARGIN, sh - 2 * MARGIN)
    bx, by, bw = MARGIN, sh - MARGIN - BLOCK, sw - 2 * MARGIN
    o.rect(bx, by, bw, BLOCK, width=0.35)
    cols = [bw * k for k in (0.0, 0.34, 0.52, 0.66, 0.78, 0.9, 1.0)]
    cells = [
        ("PARÇA", str(meta.get("title", "")), 5.5),
        ("MALZEME", str(meta.get("material", "-")), 3.8),
        ("KÜTLE", f"{fmt(meta['mass_g'])} g" if meta.get("mass_g") else "-", 3.8),
        ("ÖLÇEK", scale_label(s), 3.8),
        ("PAFTA", sheet, 3.8),
        ("TARİH", str(meta.get("date") or date.today().isoformat()), 3.4),
    ]
    for (label, value, size_), x0, x1 in zip(cells, cols, cols[1:], strict=False):
        o.line(bx + x0, by, bx + x0, by + BLOCK, "FRAME", cls="t")
        o.text(bx + x0 + 1.5, by + 4, label, 2.4, anchor="start")
        o.text(bx + x0 + 1.5, by + 12, value[: int((x1 - x0) / (size_ * 0.55))], size_, anchor="start", bold=True)
    o.line(bx, by + 17, bx + bw, by + 17, "FRAME", cls="t")
    notes = ["Ölçüler mm. Genel tolerans ISO 2768-m. Belirtilmeyen kenarları kır (0.3 mm). Üçüncü açı izdüşümü (ISO 5456-2).", *[str(n) for n in meta.get("notes", [])]]
    for k, n in enumerate(notes[:4]):
        o.text(bx + 2, by + 22 + 4.2 * k, n, 3.0, anchor="start")
    o.text(bx + bw - 2, by + BLOCK - 2, "NEML", 3.0, anchor="end")

    style = (
        "text{font-family:Arial,Helvetica,sans-serif;fill:#000}"
        ".v{fill:none;stroke:#000;stroke-width:.5;stroke-linecap:round}"
        ".h{fill:none;stroke:#000;stroke-width:.25;stroke-dasharray:2 1}"
        ".t{stroke:#000;stroke-width:.25}.d{stroke:#000;stroke-width:.25;marker-start:url(#a);marker-end:url(#a)}"
    )
    defs = (
        '<defs><marker id="a" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">'
        '<path d="M0 0 L10 5 L0 10 Z" fill="#000"/></marker>'
        '<pattern id="hatch" width="2" height="2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="2" stroke="#000" stroke-width=".2"/></pattern></defs>'
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{sw}mm" height="{sh}mm" viewBox="0 0 {sw} {sh}">'
        f'<style>{style}</style>{defs}<rect width="{sw}" height="{sh}" fill="#fff"/>' + "".join(o.svg) + "</svg>"
    )
    dxf = "0\nSECTION\n2\nENTITIES\n" + "".join(o.dxf) + "0\nENDSEC\n0\nEOF\n"
    return svg, dxf, {"sheet": sheet, "scale": scale_label(s)}
