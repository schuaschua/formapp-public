#!/usr/bin/env python3
"""Compact a Da Vinci diagram: place its nodes from `<name>.layout.json`, draw every arrow as a
straight line coloured by its destination, and re-export PNG and SVG.

The kit's builder (`.claude/skills/agent-davinci/scripts/build-drawio.py`) routes every arrow in
its own lane so nothing crosses, which makes a busy diagram very large. This is a layout-only
pass over the `.drawio` it wrote: content, citations and the drift stamp are untouched. Run it
after every rebuild:

    uv run .claude/skills/agent-davinci/scripts/build-drawio.py . docs/architecture/diagrams/<name>.model.json --force --export none
    python3 scripts/compact_diagram.py docs/architecture/diagrams/<name>.drawio

`<name>.layout.json`:
    {"nodes": {"<node id>": [centre x, centre y], ...},      every node of the model
     "colours": {"<node id>": "#RRGGBB", ...},               arrow colour per destination
     "label_at": {"<from>><to>": -0.4}}                      optional: slide a label along its arrow (-1..1)

An icon or a person carries its label underneath, so an arrow that leaves or arrives from below
starts or ends under that label instead of running through it; a mostly sideways arrow uses the
left or right edge.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PAPER = {"A4": (827, 1169), "A3": (1169, 1654), "A2": (1654, 2339)}  # page units, portrait
MARGIN = 20
HEADER = 70  # title and stamp
GROUP_PAD = (22, 52, 22, 18)  # left, top (room for the group's label), right, bottom
LABEL_BELOW = (150, 64)  # width and default height of the label under an icon or a person
SIDEWAYS = 0.6  # an arrow no steeper than this leaves and arrives by the side of an icon
PAIR_OFFSET = 24  # how far apart the two arrows of a there-and-back pair run
DEFAULT_COLOUR = "#555555"


def cell_of(obj: ET.Element) -> ET.Element:
    return obj if obj.tag == "mxCell" else obj.find("mxCell")


def main(path: Path) -> int:
    layout = json.loads(path.with_suffix(".layout.json").read_text())
    model = json.loads(path.with_suffix(".model.json").read_text())
    tree = ET.parse(path)
    graph = next(tree.getroot().iter("mxGraphModel"))
    root = graph.find("root")
    objs = {o.get("id"): o for o in root}
    geo = {i: cell_of(o).find("mxGeometry") for i, o in objs.items() if cell_of(o) is not None}

    missing = [n["id"] for n in model["nodes"] if n["id"] not in layout["nodes"]]
    if missing:
        print(f"layout has no position for: {', '.join(missing)}", file=sys.stderr)
        return 1

    # --- nodes: absolute rectangle, plus the room its label takes when it hangs below ---
    rect, extent, label_h = {}, {}, {}
    for n in model["nodes"]:
        nid = "n-" + n["id"]
        w, h = float(geo[nid].get("width")), float(geo[nid].get("height"))
        cx, cy = layout["nodes"][n["id"]]
        rect[nid] = (cx - w / 2, cy - h / 2, w, h)
        below = "verticalLabelPosition=bottom" in cell_of(objs[nid]).get("style", "")
        lw = max(w, LABEL_BELOW[0]) if below else w
        if below:
            parts = [re.sub(r"<[^>]+>", "", part) for part in objs[nid].get("label", "").split("<br>")]
            label_h[nid] = 15 * sum(1 + len(part) // 25 for part in parts) + 6
        extent[nid] = (cx - lw / 2, cy - h / 2, cx + lw / 2, cy + h / 2 + label_h.get(nid, 0))

    # --- groups: the box around their members, innermost first ---
    groups = {g["id"]: g for g in model.get("groups", [])}

    def depth(gid: str) -> int:
        parent = groups[gid].get("parent")
        return 1 + depth(parent) if parent else 0

    for gid in sorted(groups, key=depth, reverse=True):
        members = [extent["n-" + n["id"]] for n in model["nodes"] if n.get("group") == gid]
        members += [extent["g-" + c] for c, g in groups.items() if g.get("parent") == gid]
        x0 = min(m[0] for m in members) - GROUP_PAD[0]
        y0 = min(m[1] for m in members) - GROUP_PAD[1]
        x1 = max(m[2] for m in members) + GROUP_PAD[2]
        y1 = max(m[3] for m in members) + GROUP_PAD[3]
        rect["g-" + gid] = (x0, y0, x1 - x0, y1 - y0)
        extent["g-" + gid] = (x0, y0, x1, y1)

    for cid, (x, y, w, h) in rect.items():
        parent = cell_of(objs[cid]).get("parent")
        px, py = rect[parent][:2] if parent in rect else (0.0, 0.0)
        geo[cid].set("x", f"{x - px:.1f}")
        geo[cid].set("y", f"{y - py:.1f}")
        geo[cid].set("width", f"{w:.1f}")
        geo[cid].set("height", f"{h:.1f}")

    # --- arrows: straight, coloured by destination; a there-and-back pair runs side by side ---
    pairs = {(e["from"], e["to"]) for e in model["edges"]}
    for obj in root:
        cell = cell_of(obj)
        if cell is None or cell.get("edge") != "1":
            continue
        src, dst = cell.get("source"), cell.get("target")
        colour = layout.get("colours", {}).get(dst[2:], DEFAULT_COLOUR)
        style = re.sub(r"(exit|entry)(X|Y|Dx|Dy|Perimeter)=[^;]*;", "", cell.get("style"))
        style = re.sub(r"(strokeColor|fontColor|strokeWidth|edgeStyle|rounded)=[^;]*;", "", style)
        style += f"edgeStyle=none;rounded=0;strokeColor={colour};fontColor={colour};strokeWidth=1.5;"
        (ax, ay, aw, ah), (bx, by, bw, bh) = rect[src], rect[dst]
        dx, dy = (bx + bw / 2) - (ax + aw / 2), (by + bh / 2) - (ay + ah / 2)
        sideways = abs(dy) <= SIDEWAYS * abs(dx)
        for end, cid, towards_x, towards_y in (("exit", src, dx, dy), ("entry", dst, -dx, -dy)):
            if cid not in label_h:
                continue  # a box: the arrow meets its edge on the way to its centre
            if sideways:
                style += f"{end}X={1 if towards_x > 0 else 0};{end}Y=0.5;{end}Perimeter=0;"
            elif towards_y < 0:
                style += f"{end}X=0.5;{end}Y=0;{end}Perimeter=0;"
            else:
                style += f"{end}X=0.5;{end}Y=1;{end}Dx=0;{end}Dy={label_h[cid]};{end}Perimeter=0;"
        cell.set("style", style)
        obj.set("label", obj.get("label", "").replace('color="#555555"', f'color="{colour}"'))
        g = geo[obj.get("id")]
        for child in list(g):
            g.remove(child)
        paired = (dst[2:], src[2:]) in pairs
        g.set("x", str(layout.get("label_at", {}).get(f"{src[2:]}>{dst[2:]}", -0.45 if paired else 0)))
        g.attrib.pop("y", None)
        if paired:
            sx, sy, tx, ty = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
            length = ((tx - sx) ** 2 + (ty - sy) ** 2) ** 0.5 or 1.0
            points = ET.SubElement(g, "Array", {"as": "points"})
            ET.SubElement(points, "mxPoint", {"x": f"{(sx + tx) / 2 - (ty - sy) / length * PAIR_OFFSET:.1f}",
                                              "y": f"{(sy + ty) / 2 + (tx - sx) / length * PAIR_OFFSET:.1f}"})

    # --- title, stamp, notes and page ---
    top = [e for k, e in extent.items() if cell_of(objs[k]).get("parent") == "1"]
    right = max(e[2] for e in top) + MARGIN
    bottom = max(e[3] for e in top) + MARGIN
    for cid in ("title", "stamp"):
        geo[cid].set("width", f"{right - MARGIN:.0f}")
    notes = objs["notes"]
    if "Arrow colour" not in notes.get("label", ""):
        notes.set("label", notes.get("label") + "<br><br>Arrow colour shows where the arrow goes: every arrow into the same "
                                               "element has that element's colour.")
    lines = sum(1 + len(re.sub(r"<[^>]+>", "", part)) // int((right - MARGIN) / 5.6)
                for part in notes.get("label").split("<br>"))
    notes_h = lines * 15 + 20
    geo["notes"].set("x", str(MARGIN))
    geo["notes"].set("y", f"{bottom:.0f}")
    geo["notes"].set("width", f"{right - MARGIN:.0f}")
    geo["notes"].set("height", f"{notes_h:.0f}")

    page = model.get("page", {})
    short, long_ = PAPER[page.get("size", "A4")]
    pw, ph = (long_, short) if page.get("orientation") == "landscape" else (short, long_)
    graph.set("pageWidth", str(pw))
    graph.set("pageHeight", str(ph))
    width, height = right + MARGIN, bottom + notes_h + MARGIN
    scale = min(1.0, pw / width, ph / height)
    objs["0"].set("page", f"{page.get('size', 'A4')} {page.get('orientation', 'portrait')} x1 at {scale:.2f}")

    ET.indent(tree)
    tree.write(path, encoding="utf-8", xml_declaration=False)
    print(json.dumps({"file": str(path), "width": round(width), "height": round(height), "page": [pw, ph],
                      "scale": round(scale, 2), "exports": export(path)}, indent=2))
    return 0


def export(path: Path) -> list[str]:
    cli = shutil.which("drawio")
    if not cli:
        return []
    written = []
    for fmt in ("png", "svg"):
        out = path.with_suffix("." + fmt)
        args = [cli, "--export", "--format", fmt, "--border", "10", *(["--scale", "2"] if fmt == "png" else []),
                "--output", str(out), str(path)]
        if subprocess.run(args, capture_output=True, text=True, timeout=180).returncode == 0:
            written.append(out.name)
    return written


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1])))
