# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later

"""KiCad 8 emitters: a circuit recipe (data) in, schematic and routed board out.

KiCad is GPL-3.0 and never enters this tree (SPEC 1.3): this module writes the
documented s-expression file format the way a text editor would. There are no
board templates: the agents describe the circuit as data, route.autoroute draws
the tracks, and the SPEC 13.2 human review still stands before any order.

`audit` is the single place where the SPEC 13.2 silent errors are caught for every
board: a device without its own decoupling capacitor, a pin left floating where the
part needs a pull-up/pull-down, one symbol name drawn with two different pinouts.
"""

import math
import uuid

# Fixed so the same parameters always produce byte-identical files (SPEC 0.6).
NAMESPACE = uuid.UUID("6f1c2d5e-8b3a-4f7c-9d21-4a6e0b8c1f33")
SCH_VERSION = "20231120"
PCB_VERSION = "20240108"
PROJECT = "neml"
FONT = "(effects (font (size 1.27 1.27)))"
HIDDEN = "(effects (font (size 1.27 1.27)) hide)"
FP_FONT = "(effects (font (size 1 1) (thickness 0.15)))"

# SPEC 13.1: >=0603 SMD or THT. There is no pad geometry for anything smaller,
# so a template physically cannot draw an 0402.
PACKAGES = {
    "0603": {"pad": (0.875, 0.95), "dx": 0.7875, "smd": True},
    "0805": {"pad": (1.15, 1.4), "dx": 0.9375, "smd": True},
    "1206": {"pad": (1.15, 1.75), "dx": 1.4747, "smd": True},
    "2512": {"pad": (2.0, 3.6), "dx": 2.9, "smd": True},
    "THT": {"pad": (1.7, 1.7), "dx": 2.54, "smd": False, "drill": 0.9},
}
SMD_PACKAGES = tuple(name for name, geo in PACKAGES.items() if geo["smd"])

RHO_CU = 1.72e-8  # ohm.m at 20 C
COPPER_OZ_M = 35e-6  # finished copper thickness of a 1 oz process


class DesignError(ValueError):
    """The board violates a SPEC 13.1 limit or a SPEC 13.2 review rule."""


def uid(*seed):
    return str(uuid.uuid5(NAMESPACE, "/".join(str(s) for s in seed)))


def _f(value):
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def trace_mohm(length_mm, width_mm, copper_oz=1):
    """DC resistance of a copper track, for the SPEC 13.2 rail simulation.

    ponytail: 20 C, no temperature rise, no via resistance. If a rail ever lands
    near the 5% limit, measure the real board and calibrate from that.
    """
    area_m2 = (width_mm * 1e-3) * (COPPER_OZ_M * copper_oz)
    return RHO_CU * (length_mm * 1e-3) / area_m2 * 1000.0


def part(
    ref,
    value,
    kind,
    pins,
    symbol=None,
    package="0603",
    part_number="",
    supplier="LCSC",
    unit_cost_try=0.0,
    lead_time_days=7,
    decouples=None,
    needs_decoupling=(),
    needs_pull=None,
    in_bom=True,
):
    """One physical part: a schematic symbol, a PCB footprint and a BOM row.

    pins             ((number, name, electrical_type, net), ...)
    decouples        ref of the device this capacitor decouples (SPEC 13.2)
    needs_decoupling rail nets this device must see a local capacitor on
    needs_pull       {net: rail} nets that must not float (SPEC 13.2)
    """
    if package not in PACKAGES:
        raise DesignError(f"SPEC 13.1: {ref}: package {package!r} is not >=0603 SMD or THT")
    if not pins:
        raise DesignError(f"{ref}: a part with no pins is not a part")
    return {
        "ref": ref,
        "value": str(value),
        "kind": kind,
        "symbol": symbol or kind,
        "package": package,
        "pins": tuple(pins),
        "nets": tuple(net for _n, _name, _type, net in pins),
        "part_number": part_number,
        "supplier": supplier,
        "unit_cost_try": float(unit_cost_try),
        "lead_time_days": int(lead_time_days),
        "decouples": decouples,
        "needs_decoupling": tuple(needs_decoupling),
        "needs_pull": dict(needs_pull or {}),
        "in_bom": bool(in_bom),
    }


def audit(parts):
    """SPEC 13.2: the silent errors that make human review mandatory.

    Fixed once here so no template can ship a device without decoupling or a
    floating pin, and so a wrong pinout cannot hide behind a reused symbol name.
    """
    problems = []
    refs = {p["ref"] for p in parts}
    caps = [p for p in parts if p["kind"] == "C"]
    resistors = [p for p in parts if p["kind"] == "R"]
    pinouts = {}
    for p in parts:
        signature = tuple((num, name, etype) for num, name, etype, _net in p["pins"])
        if pinouts.setdefault(p["symbol"], signature) != signature:
            problems.append(f"symbol {p['symbol']} is drawn with two different pinouts")
        for rail in p["needs_decoupling"]:
            if not any(
                c["decouples"] == p["ref"] and rail in c["nets"] and "GND" in c["nets"]
                for c in caps
            ):
                problems.append(f"{p['ref']} has no decoupling capacitor on {rail}")
        for net, rail in p["needs_pull"].items():
            if not any(net in r["nets"] and rail in r["nets"] for r in resistors):
                problems.append(f"{p['ref']}: {net} floats, it needs a resistor to {rail}")
    for c in caps:
        if c["decouples"] and c["decouples"] not in refs:
            problems.append(f"{c['ref']} decouples {c['decouples']}, which is not on the board")
    if problems:
        raise DesignError("SPEC 13.2: " + "; ".join(sorted(set(problems))))


def bom_rows(parts):
    """SPEC 7 bom_items rows, in schematic order, one row per distinct part.

    The parts list is the only source (SPEC 13.2). A passive with no MPN is
    identified by value and package, so 10k_0603 and 10k_THT stay two lines.
    """
    rows = {}
    for p in parts:
        if not p["in_bom"]:
            continue
        key = (p["part_number"] or f"{p['value']}_{p['package']}", p["supplier"])
        row = rows.setdefault(
            key,
            {
                "ref": [],
                "part_number": key[0],
                "qty": 0,
                "unit_cost_try": p["unit_cost_try"],
                "supplier": key[1],
                "lead_time_days": p["lead_time_days"],
            },
        )
        row["ref"].append(p["ref"])
        row["qty"] += 1
    return [{**row, "ref": " ".join(row["ref"])} for row in rows.values()]


def _grid(count, pitch_x, pitch_y, cols, x0, y0):
    return [(x0 + pitch_x * (i % cols), y0 + pitch_y * (i // cols)) for i in range(count)]


def _pin_points(pins):
    """Connection point (x, y, side) of every pin, relative to the symbol origin."""
    if len(pins) == 2:
        return {pins[0][0]: (-5.08, 0.0, "left"), pins[1][0]: (5.08, 0.0, "right")}
    top = 2.54 * (len(pins) - 1) / 2
    return {num: (-12.7, top - 2.54 * i, "left") for i, (num, *_rest) in enumerate(pins)}


def _undriven_power_nets(parts):
    """Nets feeding a power_in pin with no power_out source: KiCad ERC needs a flag."""
    driven = {net for p in parts for _n, _nm, etype, net in p["pins"] if etype == "power_out"}
    sunk = {net for p in parts for _n, _nm, etype, net in p["pins"] if etype == "power_in"}
    return sorted(sunk - driven)


def _with_power_flags(parts):
    flags = [
        part(
            f"#FLG{i + 1}",
            "PWR_FLAG",
            "FLG",
            (("1", "pwr", "power_out", net),),
            symbol="PWR_FLAG",
            package="THT",
            in_bom=False,
        )
        for i, net in enumerate(_undriven_power_nets(parts))
    ]
    return list(parts) + flags


def _lib_symbol(name, pins):
    points = _pin_points(pins)
    if len(pins) == 2:
        box = (-2.54, -1.27, 2.54, 1.27)
    else:
        half = 2.54 * (len(pins) + 1) / 2
        box = (-10.16, -half, 10.16, half)
    unit = name.split(":")[-1]  # KiCad names the unit sub-symbols without the library nickname
    out = [
        f'    (symbol "{name}"',
        "      (pin_names (offset 0.254)) (exclude_from_sim no) (in_bom yes) (on_board yes)",
        f'      (property "Reference" "U" (at 0 0 0) {FONT})',
        f'      (property "Value" "{name}" (at 0 0 0) {FONT})',
        f'      (property "Footprint" "" (at 0 0 0) {HIDDEN})',
        f'      (property "Datasheet" "" (at 0 0 0) {HIDDEN})',
        f'      (symbol "{unit}_0_1"',
        f"        (rectangle (start {_f(box[0])} {_f(box[1])}) (end {_f(box[2])} {_f(box[3])})",
        "          (stroke (width 0.254) (type default)) (fill (type background)))",
        "      )",
        f'      (symbol "{unit}_1_1"',
    ]
    for num, pin_name, etype, _net in pins:
        x, y, side = points[num]
        angle = 0 if side == "left" else 180
        out.append(
            f"        (pin {etype} line (at {_f(x)} {_f(y)} {angle}) (length 2.54)"
            f' (name "{pin_name}" {FONT}) (number "{num}" {FONT}))'
        )
    out += ["      )", "    )"]
    return out


def _symbol_instance(root, p, x, y):
    in_bom = "yes" if p["in_bom"] else "no"
    out = [
        f'    (symbol (lib_id "{PROJECT}:{p["symbol"]}") (at {_f(x)} {_f(y)} 0) (unit 1)',
        f"      (exclude_from_sim no) (in_bom {in_bom}) (on_board yes) (dnp no)",
        f'      (uuid "{uid("sym", root, p["ref"])}")',
        f'      (property "Reference" "{p["ref"]}" (at {_f(x)} {_f(y - 17.78)} 0) {FONT})',
        f'      (property "Value" "{p["value"]}" (at {_f(x)} {_f(y + 17.78)} 0) {FONT})',
        f'      (property "Footprint" "{footprint_name(p)}" (at {_f(x)} {_f(y)} 0) {HIDDEN})',
        f'      (property "MPN" "{p["part_number"]}" (at {_f(x)} {_f(y)} 0) {HIDDEN})',
    ]
    for num, *_rest in p["pins"]:
        out.append(f'      (pin "{num}" (uuid "{uid("pin", root, p["ref"], num)}"))')
    out += [
        "      (instances",
        f'        (project "{PROJECT}"',
        f'          (path "/{root}" (reference "{p["ref"]}") (unit 1))',
        "        )",
        "      )",
        "    )",
    ]
    return out


def _pin_nets(root, p, x, y):
    """A stub wire and a net label on every pin: connectivity by name, no routing."""
    out = []
    points = _pin_points(p["pins"])
    for num, _name, _etype, net in p["pins"]:
        px, py, side = points[num]
        sign = -1 if side == "left" else 1
        ax, ay = x + px, y - py  # lib symbols are Y-up, the sheet is Y-down
        bx = ax + sign * 2.54
        justify = "left" if sign > 0 else "right"
        angle = 0 if sign > 0 else 180
        effects = f"(effects (font (size 1.27 1.27)) (justify {justify} bottom))"
        out += [
            f"    (wire (pts (xy {_f(ax)} {_f(ay)}) (xy {_f(bx)} {_f(ay)}))",
            f'      (stroke (width 0) (type default)) (uuid "{uid("wire", root, p["ref"], num)}"))',
            f'    (label "{net}" (at {_f(bx)} {_f(ay)} {angle})',
            f'      {effects} (uuid "{uid("label", root, p["ref"], num)}"))',
        ]
    return out


def schematic_text(title, parts, paper="A2"):
    """A complete single sheet .kicad_sch. Runs `audit` first: no audit, no file."""
    audit(parts)
    placed = _with_power_flags(parts)
    root = uid("sch", title)
    symbols = {p["symbol"]: p["pins"] for p in placed}
    lines = [
        "(kicad_sch",
        f"  (version {SCH_VERSION})",
        f'  (generator "{PROJECT}")',
        '  (generator_version "8.0")',
        f'  (uuid "{root}")',
        f'  (paper "{paper}")',
        "  (title_block",
        f'    (title "{title}")',
        '    (company "Mustafa Gulsoy")',
        "  )",
        "  (lib_symbols",
    ]
    for name in sorted(symbols):
        lines += _lib_symbol(f"{PROJECT}:{name}", symbols[name])
    lines.append("  )")
    for p, (x, y) in zip(placed, _grid(len(placed), 50.8, 45.72, 6, 38.1, 38.1), strict=True):
        lines += _symbol_instance(root, p, x, y)
        lines += _pin_nets(root, p, x, y)
    lines += ["  (sheet_instances", '    (path "/" (page "1"))', "  )", ")", ""]
    return "\n".join(lines)


def footprint_name(p):
    if p["kind"] in ("CONN", "MOD") or not PACKAGES[p["package"]]["smd"]:
        return f"{PROJECT}:PinHeader_1x{len(p['pins'])}_2.54mm"
    if p["kind"] == "IC":
        return f"{PROJECT}:SOIC-{len(p['pins'])}_1.27mm"
    return f"{PROJECT}:{p['kind']}_{p['package']}"


def _pads(p):
    """(number, x, y, style, size, drill) for every pin of a placed part."""
    pins, geo = p["pins"], PACKAGES[p["package"]]
    if len(pins) == 2 and geo["smd"]:
        w, h = geo["pad"]
        return [
            (pins[0][0], -geo["dx"], 0.0, "smd", (w, h), None),
            (pins[1][0], geo["dx"], 0.0, "smd", (w, h), None),
        ]
    if p["kind"] == "IC" and geo["smd"]:
        per_side = math.ceil(len(pins) / 2)
        pads = []
        for i, (num, *_rest) in enumerate(pins):
            side = -1 if i < per_side else 1
            row = i if i < per_side else len(pins) - 1 - i
            y = (row - (per_side - 1) / 2) * 1.27
            pads.append((num, side * 2.7, y, "smd", (1.95, 0.6), None))
        return pads
    return [
        (num, (i - (len(pins) - 1) / 2) * 2.54, 0.0, "thru_hole", (1.7, 1.7), 0.9)
        for i, (num, *_rest) in enumerate(pins)
    ]


def _footprint(p, x, y, net_id):
    pads = _pads(p)
    span = max(abs(px) for _n, px, _py, _s, _sz, _d in pads) + 1.0
    tall = max(abs(py) for _n, _px, py, _s, _sz, _d in pads) + 1.0
    smd = all(style == "smd" for _n, _px, _py, style, _sz, _d in pads)
    numbers = [num for num, *_rest in p["pins"]]
    out = [
        f'  (footprint "{footprint_name(p)}"',
        '    (layer "F.Cu")',
        f'    (uuid "{uid("fp", p["ref"])}")',
        f"    (at {_f(x)} {_f(y)})",
        f"    (attr {'smd' if smd else 'through_hole'})",
        f'    (property "Reference" "{p["ref"]}" (at 0 {_f(-tall - 1)} 0) (layer "F.SilkS")'
        f' (uuid "{uid("fpref", p["ref"])}") {FP_FONT})',
        f'    (property "Value" "{p["value"]}" (at 0 {_f(tall + 1)} 0) (layer "F.Fab")'
        f' (uuid "{uid("fpval", p["ref"])}") {FP_FONT})',
        f"    (fp_rect (start {_f(-span)} {_f(-tall)}) (end {_f(span)} {_f(tall)})",
        "      (stroke (width 0.05) (type solid)) (fill none)"
        f' (layer "F.CrtYd") (uuid "{uid("crtyd", p["ref"])}"))',
    ]
    for num, px, py, style, (pw, ph), drill in pads:
        net = p["nets"][numbers.index(num)]
        layers = '"F.Cu" "F.Paste" "F.Mask"' if style == "smd" else '"*.Cu" "*.Mask"'
        shape = "roundrect" if style == "smd" else "circle"
        extra = " (roundrect_rratio 0.25)" if style == "smd" else f" (drill {_f(drill)})"
        out.append(
            f'    (pad "{num}" {style} {shape} (at {_f(px)} {_f(py)}) '
            f"(size {_f(pw)} {_f(ph)}){extra} (layers {layers}) "
            f'(net {net_id[net]} "{net}") (uuid "{uid("pad", p["ref"], num)}"))'
        )
    out.append("  )")
    return out


def extent(p):
    """Half width and half height (mm) of a part's courtyard."""
    pads = _pads(p)
    return (
        max(abs(px) + w / 2 for _n, px, _py, _s, (w, _h), _d in pads) + 1.0,
        max(abs(py) + h / 2 for _n, _px, py, _s, (_w, h), _d in pads) + 1.0,
    )


def autoplace(parts, overrides=None, gap=2.0, margin=5.0):
    """Centres of every board part on a shelf layout (largest first); `overrides` {ref: (x, y)} win.

    Returns (places, width, height). Parts of the shelf never share a courtyard.
    """
    board = [p for p in parts if p["kind"] != "FLG"]
    overrides = {k: (float(v[0]), float(v[1])) for k, v in (overrides or {}).items()}
    sizes = {p["ref"]: extent(p) for p in board}
    free = sorted(
        (p for p in board if p["ref"] not in overrides),
        key=lambda q: -sizes[q["ref"]][0] * sizes[q["ref"]][1],
    )
    area = sum(4 * sizes[p["ref"]][0] * sizes[p["ref"]][1] for p in free)
    row_w = max(math.sqrt(area) * 1.5, max((2 * sizes[p["ref"]][0] for p in free), default=0))
    places = dict(overrides)
    x = y = margin
    row_h = 0.0
    for p in free:
        hx, hy = sizes[p["ref"]]
        if x > margin and x + 2 * hx > margin + row_w:
            x, y, row_h = margin, y + row_h + gap, 0.0
        places[p["ref"]] = (x + hx, y + hy)
        x += 2 * hx + gap
        row_h = max(row_h, 2 * hy)
    if overrides:  # hints may overlap or sit off the board: the board is legal whatever was asked
        if not _separate(places, sizes, 0.5):
            return autoplace(parts, None, gap, margin)
        dx = margin - min(x - sizes[r][0] for r, (x, _y) in places.items())
        dy = margin - min(y - sizes[r][1] for r, (_x, y) in places.items())
        places = {r: (x + dx, y + dy) for r, (x, y) in places.items()}
    width = max((places[r][0] + sizes[r][0] for r in places), default=10.0) + margin
    height = max((places[r][1] + sizes[r][1] for r in places), default=10.0) + margin
    return places, width, height


def _separate(places, sizes, gap):
    """Push overlapping courtyards apart along the shorter way out until none overlap (in place)."""
    refs = sorted(places)
    for _ in range(400):
        moved = False
        for i, a in enumerate(refs):
            for b in refs[i + 1 :]:
                (xa, ya), (xb, yb) = places[a], places[b]
                ox = sizes[a][0] + sizes[b][0] + gap - abs(xb - xa)
                oy = sizes[a][1] + sizes[b][1] + gap - abs(yb - ya)
                if ox > 0 and oy > 0:
                    if ox < oy:
                        sign = ox / 2 if xb >= xa else -ox / 2
                        places[a], places[b] = (xa - sign, ya), (xb + sign, yb)
                    else:
                        sign = oy / 2 if yb >= ya else -oy / 2
                        places[a], places[b] = (xa, ya - sign), (xb, yb + sign)
                    moved = True
        if not moved:
            return True
    return False


def pcb_text(title, parts, places=None, size=None, tracks=(), vias=()):
    """A placed, netted, routed, poured 2-layer board. SPEC 13.1 allows nothing thicker.

    `places` {ref: (x, y)} overrides the shelf layout; `size` (w, h) the outline; `tracks`
    are (net, layer, (x1, y1), (x2, y2), width) and `vias` (net, (x, y), size, drill), as
    `route.autoroute` returns them.
    """
    audit(parts)
    board = [p for p in parts if p["kind"] != "FLG"]
    nets = ["", "GND"] + sorted({n for p in board for n in p["nets"]} - {"GND"})
    net_id = {net: i for i, net in enumerate(nets)}
    at, width, height = autoplace(parts, places)
    if size:
        width, height = float(size[0]), float(size[1])
    lines = [
        "(kicad_pcb",
        f"  (version {PCB_VERSION})",
        f'  (generator "{PROJECT}")',
        '  (generator_version "8.0")',
        "  (general (thickness 1.6) (legacy_teardrops no))",
        '  (paper "A4")',
        f'  (title_block (title "{title}") (company "Mustafa Gulsoy"))',
        "  (layers",
        '    (0 "F.Cu" signal)',
        '    (31 "B.Cu" signal)',
        '    (32 "B.Adhes" user "B.Adhesive")',
        '    (33 "F.Adhes" user "F.Adhesive")',
        '    (34 "B.Paste" user)',
        '    (35 "F.Paste" user)',
        '    (36 "B.SilkS" user "B.Silkscreen")',
        '    (37 "F.SilkS" user "F.Silkscreen")',
        '    (38 "B.Mask" user)',
        '    (39 "F.Mask" user)',
        '    (40 "Dwgs.User" user "User.Drawings")',
        '    (41 "Cmts.User" user "User.Comments")',
        '    (44 "Edge.Cuts" user)',
        '    (45 "Margin" user)',
        '    (46 "B.CrtYd" user "B.Courtyard")',
        '    (47 "F.CrtYd" user "F.Courtyard")',
        '    (48 "B.Fab" user)',
        '    (49 "F.Fab" user)',
        "  )",
        "  (setup (pad_to_mask_clearance 0.05) (allow_soldermask_bridges_in_footprints no))",
    ]
    for net, index in sorted(net_id.items(), key=lambda kv: kv[1]):
        lines.append(f'  (net {index} "{net}")')
    for p in board:
        x, y = at[p["ref"]]
        lines += _footprint(p, x, y, net_id)
    for i, (net, layer, (x1, y1), (x2, y2), w) in enumerate(tracks):
        lines.append(
            f"  (segment (start {_f(x1)} {_f(y1)}) (end {_f(x2)} {_f(y2)}) (width {_f(w)}) "
            f'(layer "{layer}") (net {net_id[net]}) (uuid "{uid("seg", title, i)}"))'
        )
    for i, (net, (x, y), vsize, drill) in enumerate(vias):
        lines.append(
            f"  (via (at {_f(x)} {_f(y)}) (size {_f(vsize)}) (drill {_f(drill)}) "
            f'(layers "F.Cu" "B.Cu") (net {net_id[net]}) (uuid "{uid("via", title, i)}"))'
        )
    corners = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]
    for i, (sx, sy) in enumerate(corners):
        ex, ey = corners[(i + 1) % 4]
        lines.append(
            f"  (gr_line (start {_f(sx)} {_f(sy)}) (end {_f(ex)} {_f(ey)}) "
            f'(stroke (width 0.1) (type solid)) (layer "Edge.Cuts") '
            f'(uuid "{uid("edge", title, i)}"))'
        )
    polygon = " ".join(f"(xy {_f(px)} {_f(py)})" for px, py in corners)
    lines += [
        "  (zone",
        f'    (net {net_id["GND"]}) (net_name "GND")',
        '    (layer "B.Cu")',
        f'    (uuid "{uid("zone", title)}")',
        "    (hatch edge 0.5)",
        "    (connect_pads (clearance 0.5))",
        "    (min_thickness 0.25)",
        "    (filled_areas_thickness no)",
        "    (fill (thermal_gap 0.5) (thermal_bridge_width 0.5))",
        f"    (polygon (pts {polygon}))",
        "  )",
        ")",
        "",
    ]
    return "\n".join(lines)


def spice_text(title, lines, nodes):
    """An ngspice batch deck.

    `print` inside a control block writes `v(node) = value`, which is the shape
    the SPEC 13.2 rail check parses out of the log.
    """
    return "\n".join(
        [
            f"* {title} - SPEC 13.2 power rail check",
            *lines,
            ".control",
            "op",
            "print " + " ".join(f"v({node})" for node in nodes),
            ".endc",
            ".end",
            "",
        ]
    )
