# SPDX-License-Identifier: Apache-2.0
"""Generate the memory documentation SVGs (committed, reproducible).

Emits two static SVGs (GitHub renders them inline, scalable, no binary blobs):
  * docs/assets/memory-graph-clouds.svg — the neural-graph: nodes clustered into
    colored communities ("clouds") with intra/inter-cluster edges — what the GUI
    force-graph shows.
  * docs/assets/memory-decay-curve.svg — Ebbinghaus retention computed from the
    real formula R = exp(-age / (S·strength)), one curve per reinforcement level,
    visualizing the spacing effect (recall strengthens → slower decay).

Pure stdlib, deterministic (fixed seed). Run: python3 tools/gen_memory_diagrams.py
"""
from __future__ import annotations

import math
import random
from pathlib import Path

_OUT = Path(__file__).resolve().parent.parent / "docs" / "assets"
_BG = "#15171c"
_PALETTE = ["#4f9cf9", "#f97362", "#5fd07d", "#c77dff", "#f7b955", "#46c8c8"]
_FONT = "font-family='ui-sans-serif,Segoe UI,Helvetica,Arial,sans-serif'"


def _graph_svg() -> str:
    rng = random.Random(20260701)
    w, h = 900, 540
    # community centers + node counts (importance-varied sizes)
    clusters = [
        (190, 200, 11, "alpha"), (470, 150, 13, "beta"), (720, 250, 10, "gamma"),
        (300, 410, 9, "delta"), (620, 430, 8, "epsilon"),
    ]
    nodes: list[tuple[float, float, float, int]] = []  # x,y,r,community
    cluster_nodes: list[list[int]] = []
    for ci, (cx, cy, n, _name) in enumerate(clusters):
        idxs = []
        for _ in range(n):
            ang = rng.uniform(0, 2 * math.pi)
            rad = rng.uniform(8, 78)
            x = cx + rad * math.cos(ang)
            y = cy + rad * math.sin(ang)
            r = rng.choice([4, 4, 5, 5, 6, 7, 9])  # importance-varied
            idxs.append(len(nodes))
            nodes.append((x, y, r, ci))
        cluster_nodes.append(idxs)

    edges: list[tuple[int, int, bool]] = []  # a,b,intra
    for idxs in cluster_nodes:  # dense intra-cluster
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                if rng.random() < 0.28:
                    edges.append((idxs[i], idxs[j], True))
    for _ in range(7):  # a few inter-cluster bridges
        ca, cb = rng.sample(range(len(clusters)), 2)
        edges.append((rng.choice(cluster_nodes[ca]), rng.choice(cluster_nodes[cb]), False))

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' "
        f"width='{w}' height='{h}' role='img' aria-label='Memory neural graph'>",
        f"<rect width='{w}' height='{h}' rx='14' fill='{_BG}'/>",
        f"<text x='28' y='40' fill='#e8eaed' font-size='22' font-weight='700' {_FONT}>"
        "Neural-graph memory — knowledge clusters into clouds</text>",
        f"<text x='28' y='62' fill='#9aa0a6' font-size='13' {_FONT}>"
        "nodes = memories (size = importance) · edges = similar_to / co_access "
        "(width = strength) · colors = communities</text>",
    ]
    for a, b, intra in edges:  # edges under nodes
        x1, y1, _r1, _c1 = nodes[a]
        x2, y2, _r2, _c2 = nodes[b]
        col = "#3a3f47" if intra else "#5b6470"
        wdt = 1.1 if intra else 1.8
        dash = "" if intra else " stroke-dasharray='4 3'"
        parts.append(
            f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
            f"stroke='{col}' stroke-width='{wdt}' stroke-opacity='0.55'{dash}/>"
        )
    for x, y, r, c in nodes:
        col = _PALETTE[c % len(_PALETTE)]
        parts.append(
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r}' fill='{col}' "
            f"stroke='#0d0f12' stroke-width='1.2'/>"
        )
    # legend
    lx, ly = 28, h - 28
    for i, (_cx, _cy, _n, name) in enumerate(clusters):
        cx = lx + i * 150
        parts.append(f"<circle cx='{cx}' cy='{ly}' r='6' fill='{_PALETTE[i % len(_PALETTE)]}'/>")
        parts.append(
            f"<text x='{cx + 12}' y='{ly + 4}' fill='#c7ccd1' font-size='12' {_FONT}>"
            f"cloud {name}</text>"
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _decay_svg() -> str:
    w, h = 760, 440
    m = {"l": 64, "r": 24, "t": 64, "b": 56}
    pw, ph = w - m["l"] - m["r"], h - m["t"] - m["b"]
    days_max = 14.0
    s_day = 1.0  # EBBINGHAUS_S = 1 day, in these units

    def px(t: float) -> float:
        return m["l"] + (t / days_max) * pw

    def py(r: float) -> float:
        return m["t"] + (1 - r) * ph

    curves = [  # (strength, recalls-label, color)
        (1.0, "never recalled (strength 1.0)", _PALETTE[1]),
        (1.0 + math.log1p(1), "recalled 1× (1.69)", _PALETTE[0]),
        (1.0 + math.log1p(5), "recalled 5× (2.79)", _PALETTE[2]),
    ]
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' "
        f"width='{w}' height='{h}' role='img' aria-label='Ebbinghaus retention'>",
        f"<rect width='{w}' height='{h}' rx='14' fill='{_BG}'/>",
        f"<text x='28' y='38' fill='#e8eaed' font-size='20' font-weight='700' {_FONT}>"
        "Ebbinghaus retention — retrieval slows decay (spacing effect)</text>",
    ]
    # axes + gridlines
    for gx in range(0, 15, 2):
        x = px(gx)
        parts.append(f"<line x1='{x:.1f}' y1='{m['t']}' x2='{x:.1f}' y2='{m['t'] + ph}' stroke='#262a31' stroke-width='1'/>")
        parts.append(f"<text x='{x:.1f}' y='{m['t'] + ph + 20}' fill='#9aa0a6' font-size='11' text-anchor='middle' {_FONT}>{gx}d</text>")
    for gy in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = py(gy)
        parts.append(f"<line x1='{m['l']}' y1='{y:.1f}' x2='{m['l'] + pw}' y2='{y:.1f}' stroke='#262a31' stroke-width='1'/>")
        parts.append(f"<text x='{m['l'] - 10}' y='{y + 4:.1f}' fill='#9aa0a6' font-size='11' text-anchor='end' {_FONT}>{gy:.2f}</text>")
    parts.append(f"<text x='{m['l'] + pw / 2:.0f}' y='{h - 12}' fill='#c7ccd1' font-size='12' text-anchor='middle' {_FONT}>time since last access</text>")
    for si, (strength, label, color) in enumerate(curves):
        pts = []
        t = 0.0
        while t <= days_max + 1e-9:
            r = math.exp(-t / (s_day * strength))
            pts.append(f"{px(t):.1f},{py(r):.1f}")
            t += 0.25
        parts.append(f"<polyline points='{' '.join(pts)}' fill='none' stroke='{color}' stroke-width='2.4'/>")
        ly = m["t"] + 16 + si * 20
        parts.append(f"<line x1='{m['l'] + pw - 220}' y1='{ly}' x2='{m['l'] + pw - 198}' y2='{ly}' stroke='{color}' stroke-width='3'/>")
        parts.append(f"<text x='{m['l'] + pw - 192}' y='{ly + 4}' fill='#c7ccd1' font-size='12' {_FONT}>{label}</text>")
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "memory-graph-clouds.svg").write_text(_graph_svg(), encoding="utf-8")
    (_OUT / "memory-decay-curve.svg").write_text(_decay_svg(), encoding="utf-8")
    print("wrote", _OUT / "memory-graph-clouds.svg")
    print("wrote", _OUT / "memory-decay-curve.svg")


if __name__ == "__main__":
    main()
