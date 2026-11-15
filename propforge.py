#!/usr/bin/env python3
"""
propforge - procedural low-poly game props in one file, zero dependencies.

    python propforge.py --count 40 --out assets/props

Writes game-ready .glb files (Y-up, origin at bottom-centre, flat shading,
materials only - no textures, no UVs) plus manifest.json.

Propforge 0.1.0 - MIT licence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import struct
import sys

VERSION = "0.1.0"

# --------------------------------------------------------------------------
# colour
# --------------------------------------------------------------------------

PALETTE = {
    "wood": "#8b5a2b",
    "wood_light": "#b5854f",
    "wood_dark": "#5d3a1a",
    "metal": "#8892a0",
    "metal_dark": "#4a5560",
    "rust": "#a15c33",
    "red": "#c23b32",
    "dark_red": "#8c2a24",
    "blue": "#2f5d8a",
    "green": "#3f6b45",
    "concrete": "#9aa0a2",
    "concrete_dark": "#6f7577",
    "leaf": "#3f7a3a",
    "leaf_dark": "#2c5c2e",
    "leaf_light": "#5a9c46",
    "pine": "#2f5d3f",
    "rock": "#7d7f7a",
    "rock_dark": "#5c5f5b",
    "white": "#e8e8e4",
    "black": "#26262a",
    "yellow": "#e0b33c",
    "orange": "#d97730",
    "glass": "#5f7f8c",
    "soil": "#4a3521",
    "sand": "#c9b184",
}


def hex_rgb(value):
    if isinstance(value, tuple):
        return value
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# --------------------------------------------------------------------------
# mesh
# --------------------------------------------------------------------------

class Mesh:
    """Triangle soup grouped by material key."""

    def __init__(self):
        self.groups = {}

    def mat(self, color, rough=0.85, metal=0.0, emissive=0.0):
        r, g, b = hex_rgb(color)
        key = (round(r, 4), round(g, 4), round(b, 4),
               round(rough, 2), round(metal, 2), round(emissive, 2))
        self.groups.setdefault(key, [])
        return key

    def tri(self, key, a, b, c):
        self.groups[key].append((a, b, c))

    def quad(self, key, a, b, c, d):
        self.groups[key].append((a, b, c))
        self.groups[key].append((a, c, d))

    def tris(self):
        return sum(len(v) for v in self.groups.values())

    def bounds(self):
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for tris in self.groups.values():
            for tri in tris:
                for v in tri:
                    for i in range(3):
                        lo[i] = min(lo[i], v[i])
                        hi[i] = max(hi[i], v[i])
        if lo[0] == float("inf"):
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        return tuple(lo), tuple(hi)

    def finish(self):
        """Centre on X/Z, drop to the ground plane (y=0)."""
        lo, hi = self.bounds()
        dx = -(lo[0] + hi[0]) / 2.0
        dz = -(lo[2] + hi[2]) / 2.0
        dy = -lo[1]
        for key, tris in self.groups.items():
            self.groups[key] = [
                tuple((x + dx, y + dy, z + dz) for (x, y, z) in tri) for tri in tris
            ]
        return self


# --------------------------------------------------------------------------
# geometry primitives (everything is Y-up, metres)
# --------------------------------------------------------------------------

def _rot(yaw=0.0, pitch=0.0, roll=0.0):
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    return (
        (cy * cr + sy * sp * sr, -cy * sr + sy * sp * cr, sy * cp),
        (cp * sr, cp * cr, -sp),
        (-sy * cr + cy * sp * sr, sy * sr + cy * sp * cr, cy * cp),
    )


def _apply(r, center, v):
    return tuple(center[i] + r[i][0] * v[0] + r[i][1] * v[1] + r[i][2] * v[2]
                 for i in range(3))


def box(m, key, center, size, yaw=0.0, pitch=0.0, roll=0.0):
    """Axis box, optionally rotated. center is the box centre."""
    r = _rot(yaw, pitch, roll)
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    v = [
        _apply(r, center, (-hx, -hy, -hz)),
        _apply(r, center, (hx, -hy, -hz)),
        _apply(r, center, (-hx, hy, -hz)),
        _apply(r, center, (hx, hy, -hz)),
        _apply(r, center, (-hx, -hy, hz)),
        _apply(r, center, (hx, -hy, hz)),
        _apply(r, center, (-hx, hy, hz)),
        _apply(r, center, (hx, hy, hz)),
    ]
    for a, b, c in ((0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6),
                    (0, 1, 5), (0, 5, 4), (2, 6, 7), (2, 7, 3),
                    (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5)):
        m.tri(key, v[a], v[b], v[c])


def cyl(m, key, base, r_bot, r_top, h, segs=12, yaw=0.0, pitch=0.0, caps=True,
        roll=0.0):
    """Cylinder / cone standing on `base`, growing along local +Y."""
    r = _rot(yaw, pitch, roll)

    def p(ang, rad, z):
        return _apply(r, base, (math.cos(ang) * rad, z, math.sin(ang) * rad))

    bot = [p(2 * math.pi * i / segs, r_bot, 0.0) for i in range(segs)]
    top = [p(2 * math.pi * i / segs, r_top, h) for i in range(segs)]
    flat = r_top < 1e-6
    for i in range(segs):
        j = (i + 1) % segs
        if flat:
            m.tri(key, bot[i], bot[j], top[i])
        else:
            m.quad(key, bot[i], bot[j], top[j], top[i])
    if caps:
        lo = _apply(r, base, (0.0, 0.0, 0.0))
        hi = _apply(r, base, (0.0, h, 0.0))
        for i in range(segs):
            j = (i + 1) % segs
            if r_bot > 1e-6:
                m.tri(key, bot[j], bot[i], lo)
            if not flat:
                m.tri(key, top[i], top[j], hi)


_PHI = (1.0 + 5.0 ** 0.5) / 2.0
_ICO_V = [(-1, _PHI, 0), (1, _PHI, 0), (-1, -_PHI, 0), (1, -_PHI, 0),
          (0, -1, _PHI), (0, 1, _PHI), (0, -1, -_PHI), (0, 1, -_PHI),
          (_PHI, 0, -1), (_PHI, 0, 1), (-_PHI, 0, -1), (-_PHI, 0, 1)]
_ICO_F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
          (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
          (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
          (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]


def _norm(v):
    d = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / d, v[1] / d, v[2] / d)


def _ico_faces(subdiv):
    verts = [_norm(v) for v in _ICO_V]
    faces = list(_ICO_F)
    for _ in range(max(0, subdiv)):
        cache = {}
        new_faces = []

        def mid(a, b):
            k = (min(a, b), max(a, b))
            if k not in cache:
                va, vb = verts[a], verts[b]
                verts.append(_norm(((va[0] + vb[0]) / 2, (va[1] + vb[1]) / 2,
                                    (va[2] + vb[2]) / 2)))
                cache[k] = len(verts) - 1
            return cache[k]

        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            new_faces += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new_faces
    return verts, faces


def blob(m, key, center, radius, scale=(1.0, 1.0, 1.0), subdiv=1, yaw=0.0):
    """Squashed icosphere - rocks, foliage, bushes."""
    verts, faces = _ico_faces(subdiv)
    r = _rot(yaw)
    pts = [_apply(r, center, (v[0] * radius * scale[0],
                              v[1] * radius * scale[1],
                              v[2] * radius * scale[2])) for v in verts]
    for a, b, c in faces:
        m.tri(key, pts[a], pts[b], pts[c])


# --------------------------------------------------------------------------
# prop families.  every builder returns a Mesh standing on y=0.
# --------------------------------------------------------------------------

def _wobble(rng, amount):
    return 1.0 + rng.uniform(-amount, amount)


def barrel(rng):
    m = Mesh()
    body = m.mat(rng.choice([PALETTE["rust"], PALETTE["blue"],
                             PALETTE["green"], PALETTE["red"]]), 0.75, 0.35)
    band = m.mat(PALETTE["metal_dark"], 0.55, 0.7)
    h = rng.uniform(0.88, 1.05)
    r = rng.uniform(0.28, 0.33)
    cyl(m, body, (0, 0.15, 0), r * 0.93, r, h * 0.5, 14)
    cyl(m, body, (0, h * 0.5, 0), r, r * 0.93, h * 0.5, 14)
    for z in (0.1, 0.45, 0.85):
        cyl(m, band, (0, h * z, 0), r * 1.035, r * 1.035, h * 0.05, 14)
    cyl(m, band, (0, h, 0), r * 0.95, r * 0.9, 0.03, 14)
    cyl(m, band, (0, 0.0, 0), r * 0.95, r * 0.95, 0.03, 14)
    return m


def crate(rng):
    m = Mesh()
    wood = m.mat(rng.choice([PALETTE["wood"], PALETTE["wood_light"]]), 0.85)
    dark = m.mat(PALETTE["wood_dark"], 0.85)
    s = rng.uniform(0.62, 0.86)
    box(m, wood, (0, s / 2, 0), (s, s, s))
    t = s * 0.09
    for sx in (-1, 1):
        for sz in (-1, 1):
            box(m, dark, (sx * (s / 2 - t / 2), s / 2, sz * (s / 2 - t / 2)),
                (t, s, t))
    for y in (s * 0.2, s * 0.8):
        box(m, dark, (0, y, s / 2), (s, t, t * 0.7))
        box(m, dark, (0, y, -s / 2), (s, t, t * 0.7))
        box(m, dark, (s / 2, y, 0), (t * 0.7, t, s))
        box(m, dark, (-s / 2, y, 0), (t * 0.7, t, s))
    return m


def pallet(rng):
    m = Mesh()
    wood = m.mat(PALETTE["wood_light"], 0.9)
    dark = m.mat(PALETTE["wood_dark"], 0.9)
    w, d = 1.2, 1.0
    for i in range(3):
        box(m, dark, ((i - 1) * (w / 2 - 0.06), 0.05, 0), (0.09, 0.1, d))
    for i in range(5):
        box(m, wood, (0, 0.12, (i - 2) * (d / 5)), (w, 0.035, d / 8))
    for i in range(5):
        box(m, wood, (0, 0.02, (i - 2) * (d / 5)), (w, 0.03, d / 8))
    return m


def tree_pine(rng):
    m = Mesh()
    trunk = m.mat(PALETTE["wood_dark"], 0.9)
    leaf = m.mat(rng.choice([PALETTE["pine"], PALETTE["leaf_dark"]]), 0.85)
    h = rng.uniform(3.0, 4.6)
    cyl(m, trunk, (0, 0, 0), 0.16, 0.11, h * 0.45, 8)
    tiers = rng.randint(3, 4)
    for i in range(tiers):
        t = i / tiers
        y = h * 0.22 + t * h * 0.62
        r = h * 0.26 * (1.0 - t * 0.72)
        cyl(m, leaf, (0, y, 0), r, 0.0, h * 0.28, 9)
    return m


def tree_round(rng):
    m = Mesh()
    trunk = m.mat(PALETTE["wood"], 0.9)
    leaf = m.mat(rng.choice([PALETTE["leaf"], PALETTE["leaf_light"]]), 0.85)
    h = rng.uniform(2.6, 3.8)
    cyl(m, trunk, (0, 0, 0), 0.2, 0.13, h * 0.55, 8)
    top = h * 0.62
    for i in range(rng.randint(3, 4)):
        a = rng.uniform(0, 6.28)
        rad = rng.uniform(0.5, 0.85)
        blob(m, leaf, (math.cos(a) * rad * 0.5, top + rng.uniform(0, 0.5),
                       math.sin(a) * rad * 0.5),
             rng.uniform(0.55, 0.8), (1.0, 0.85, 1.0), 1, yaw=rng.uniform(0, 3))
    return m


def bush(rng):
    m = Mesh()
    leaf = m.mat(rng.choice([PALETTE["leaf"], PALETTE["leaf_dark"]]), 0.9)
    for _ in range(rng.randint(2, 4)):
        blob(m, leaf, (rng.uniform(-0.25, 0.25), rng.uniform(0.15, 0.4),
                       rng.uniform(-0.25, 0.25)),
             rng.uniform(0.22, 0.4), (1.0, 0.8, 1.0), 1, yaw=rng.uniform(0, 3))
    return m


def rock(rng):
    m = Mesh()
    stone = m.mat(rng.choice([PALETTE["rock"], PALETTE["rock_dark"]]), 0.95)
    for i in range(rng.randint(1, 3)):
        s = rng.uniform(0.35, 0.7) if i == 0 else rng.uniform(0.15, 0.35)
        blob(m, stone, (rng.uniform(-0.2, 0.2), s * 0.55,
                        rng.uniform(-0.2, 0.2)),
             s, (1.2, 0.7, 1.0), 1, yaw=rng.uniform(0, 3))
    return m


def fence(rng):
    m = Mesh()
    wood = m.mat(rng.choice([PALETTE["wood"], PALETTE["wood_light"]]), 0.9)
    w = rng.uniform(1.6, 2.4)
    h = rng.uniform(0.9, 1.2)
    for x in (-w / 2, w / 2):
        box(m, wood, (x, h / 2, 0), (0.1, h, 0.1))
    for y in (h * 0.35, h * 0.72):
        box(m, wood, (0, y, 0), (w, 0.09, 0.05))
    return m


def street_lamp(rng):
    m = Mesh()
    post = m.mat(PALETTE["metal_dark"], 0.5, 0.8)
    glass = m.mat(rng.choice(["#ffe9b0", "#fff3cf"]), 0.4, 0.0, 2.5)
    h = rng.uniform(3.8, 4.6)
    cyl(m, post, (0, 0, 0), 0.1, 0.075, h, 8)
    cyl(m, post, (0, 0, 0), 0.16, 0.14, 0.18, 8)
    arm = 0.55
    box(m, post, (arm / 2, h, 0), (arm, 0.07, 0.07))
    box(m, post, (arm, h - 0.06, 0), (0.34, 0.12, 0.3))
    box(m, glass, (arm, h - 0.13, 0), (0.28, 0.06, 0.24))
    return m


def bench(rng):
    m = Mesh()
    wood = m.mat(rng.choice([PALETTE["wood"], PALETTE["wood_light"]]), 0.9)
    iron = m.mat(PALETTE["metal_dark"], 0.5, 0.8)
    w = rng.uniform(1.5, 2.0)
    box(m, wood, (0, 0.45, 0), (w, 0.06, 0.46))
    box(m, wood, (0, 0.72, -0.2), (w, 0.34, 0.05))
    for x in (-w / 2 + 0.12, w / 2 - 0.12):
        box(m, iron, (x, 0.22, 0), (0.07, 0.44, 0.42))
        box(m, iron, (x, 0.6, -0.2), (0.06, 0.4, 0.05))
    return m


def dumpster(rng):
    m = Mesh()
    body = m.mat(rng.choice([PALETTE["green"], PALETTE["blue"], PALETTE["dark_red"]]),
                 0.7, 0.3)
    lid = m.mat(PALETTE["metal_dark"], 0.6, 0.5)
    w, d, h = rng.uniform(1.6, 2.0), 1.1, rng.uniform(1.1, 1.3)
    box(m, body, (0, h / 2, 0), (w, h, d))
    box(m, lid, (0, h + 0.05, 0.02), (w * 1.02, 0.08, d * 0.75), pitch=0.06)
    for x in (-w / 2 + 0.15, w / 2 - 0.15):
        box(m, lid, (x, h * 0.75, d / 2 + 0.02), (0.08, h * 0.5, 0.06))
    for x in (-w / 2 + 0.2, w / 2 - 0.2):
        cyl(m, lid, (x, 0.05, d / 2 - 0.1), 0.1, 0.1, 0.06, 8, pitch=math.pi / 2)
    return m


def traffic_cone(rng):
    m = Mesh()
    orange = m.mat(PALETTE["orange"], 0.8)
    white = m.mat(PALETTE["white"], 0.8)
    s = rng.uniform(0.9, 1.1)
    box(m, orange, (0, 0.02, 0), (0.38 * s, 0.04, 0.38 * s))
    cyl(m, orange, (0, 0.04, 0), 0.16 * s, 0.03 * s, 0.55 * s, 10)
    cyl(m, white, (0, 0.3 * s, 0), 0.085 * s, 0.06 * s, 0.09 * s, 10)
    return m


def barrier(rng):
    m = Mesh()
    wood = m.mat(PALETTE["wood"], 0.9)
    red = m.mat(PALETTE["red"], 0.85)
    white = m.mat(PALETTE["white"], 0.85)
    w = rng.uniform(1.4, 1.9)
    for x in (-w / 2 + 0.12, w / 2 - 0.12):
        box(m, wood, (x, 0.5, 0), (0.09, 1.0, 0.09))
        box(m, wood, (x, 0.03, 0), (0.12, 0.06, 0.6))
    box(m, red, (0, 0.95, 0), (w, 0.28, 0.07))
    n = 5
    for i in range(n):
        if i % 2 == 0:
            continue
        box(m, white, (-w / 2 + w * (i + 0.5) / n, 0.95, 0.045),
            (w / n * 0.9, 0.26, 0.005))
    return m


def planter(rng):
    m = Mesh()
    pot = m.mat(rng.choice([PALETTE["concrete"], PALETTE["wood_dark"]]), 0.9)
    soil = m.mat(PALETTE["soil"], 0.95)
    leaf = m.mat(PALETTE["leaf"], 0.9)
    w, d, h = rng.uniform(0.8, 1.1), rng.uniform(0.55, 0.7), rng.uniform(0.45, 0.6)
    box(m, pot, (0, h / 2, 0), (w, h, d))
    box(m, soil, (0, h - 0.03, 0), (w * 0.92, 0.06, d * 0.9))
    for i in range(rng.randint(2, 4)):
        blob(m, leaf, (rng.uniform(-w * 0.3, w * 0.3), h + rng.uniform(0.1, 0.3),
                       rng.uniform(-d * 0.25, d * 0.25)),
             rng.uniform(0.15, 0.26), (1.0, 0.9, 1.0), 1, yaw=rng.uniform(0, 3))
    return m


def mailbox(rng):
    m = Mesh()
    post = m.mat(PALETTE["wood_dark"], 0.9)
    body = m.mat(rng.choice([PALETTE["blue"], PALETTE["metal"], PALETTE["red"]]),
                 0.6, 0.3)
    red = m.mat(PALETTE["red"], 0.8)
    h = rng.uniform(0.9, 1.1)
    box(m, post, (0, h / 2, 0), (0.09, h, 0.09))
    box(m, body, (0, h + 0.14, 0), (0.3, 0.24, 0.44))
    cyl(m, body, (0, h + 0.26, 0), 0.15, 0.15, 0.44, 10, pitch=math.pi / 2,
        yaw=math.pi / 2)
    box(m, red, (0.17, h + 0.22, 0.1), (0.02, 0.18, 0.06))
    return m


def hydrant(rng):
    m = Mesh()
    body = m.mat(rng.choice([PALETTE["red"], PALETTE["yellow"]]), 0.7)
    cap = m.mat(PALETTE["metal_dark"], 0.5, 0.7)
    h = rng.uniform(0.5, 0.65)
    cyl(m, body, (0, 0, 0), 0.15, 0.14, h, 10)
    cyl(m, cap, (0, h, 0), 0.14, 0.08, 0.12, 10)
    cyl(m, cap, (0, h + 0.1, 0), 0.05, 0.04, 0.06, 8)
    for s in (-1, 1):
        cyl(m, cap, (s * 0.13, h * 0.62, 0), 0.06, 0.06, 0.09, 8,
            roll=-s * math.pi / 2)
        cyl(m, cap, (s * 0.13, h * 0.62, 0), 0.075, 0.075, 0.02, 8,
            roll=-s * math.pi / 2)
    return m


def ac_unit(rng):
    m = Mesh()
    shell = m.mat(rng.choice([PALETTE["metal"], PALETTE["concrete"]]), 0.6, 0.2)
    dark = m.mat(PALETTE["metal_dark"], 0.5, 0.6)
    w, d, h = rng.uniform(0.8, 1.0), 0.5, rng.uniform(0.6, 0.75)
    box(m, shell, (0, h / 2, 0), (w, h, d))
    cyl(m, dark, (0, h / 2, d / 2), 0.18, 0.18, 0.02, 12, pitch=math.pi / 2)
    for i in range(4):
        box(m, dark, (0, 0.12 + i * 0.13, d / 2 + 0.01), (w * 0.8, 0.02, 0.02))
    return m


def generator(rng):
    m = Mesh()
    shell = m.mat(rng.choice([PALETTE["yellow"], PALETTE["red"]]), 0.7)
    dark = m.mat(PALETTE["metal_dark"], 0.5, 0.7)
    w, d, h = 0.95, 0.6, 0.55
    box(m, shell, (0, h / 2 + 0.06, 0), (w, h, d))
    box(m, dark, (0, 0.03, 0), (w * 0.9, 0.06, d * 0.9))
    cyl(m, dark, (w * 0.3, h + 0.06, -d * 0.2), 0.045, 0.045, 0.28, 8)
    box(m, dark, (0, h + 0.12, d * 0.35), (0.4, 0.05, 0.14))
    for s in (-1, 1):
        box(m, dark, (s * w * 0.42, 0.16, 0), (0.06, 0.1, d * 0.6))
    return m


def table(rng):
    m = Mesh()
    wood = m.mat(rng.choice([PALETTE["wood"], PALETTE["wood_light"]]), 0.85)
    w, d, h = rng.uniform(1.0, 1.4), rng.uniform(0.6, 0.85), rng.uniform(0.7, 0.78)
    box(m, wood, (0, h, 0), (w, 0.06, d))
    for sx in (-1, 1):
        for sz in (-1, 1):
            box(m, wood, (sx * (w / 2 - 0.08), (h - 0.03) / 2, sz * (d / 2 - 0.08)),
                (0.08, h - 0.03, 0.08))
    return m


def chair(rng):
    m = Mesh()
    wood = m.mat(PALETTE["wood"], 0.85)
    w, d = 0.45, 0.45
    box(m, wood, (0, 0.45, 0), (w, 0.05, d))
    box(m, wood, (0, 0.7, -d / 2 + 0.03), (w, 0.45, 0.05))
    for sx in (-1, 1):
        for sz in (-1, 1):
            box(m, wood, (sx * (w / 2 - 0.04), 0.22, sz * (d / 2 - 0.04)),
                (0.05, 0.44, 0.05))
    return m


def sign(rng):
    m = Mesh()
    post = m.mat(PALETTE["metal_dark"], 0.5, 0.7)
    board = m.mat(rng.choice([PALETTE["white"], PALETTE["yellow"]]), 0.8)
    ink = m.mat(PALETTE["black"], 0.9)
    h = rng.uniform(1.6, 2.0)
    box(m, post, (0, h / 2, 0), (0.07, h, 0.07))
    box(m, board, (0, h - 0.05, 0), (0.72, 0.5, 0.04))
    box(m, ink, (0, h + 0.1, 0.03), (0.5, 0.07, 0.01))
    box(m, ink, (0, h - 0.02, 0.03), (0.4, 0.05, 0.01))
    box(m, ink, (0, h - 0.14, 0.03), (0.46, 0.05, 0.01))
    return m


def tire_stack(rng):
    m = Mesh()
    rubber = m.mat("#2b2b2e", 0.95)
    n = rng.randint(2, 4)
    r = rng.uniform(0.3, 0.36)
    for i in range(n):
        cyl(m, rubber, (rng.uniform(-0.03, 0.03), i * 0.2, rng.uniform(-0.03, 0.03)),
            r, r, 0.18, 12)
    return m


def sandbags(rng):
    m = Mesh()
    bag = m.mat(PALETTE["sand"], 0.95)
    for layer in range(2):
        for i in range(3 - layer):
            box(m, bag, ((i - (2 - layer) / 2) * 0.5, 0.15 + layer * 0.28, 0),
                (0.46, 0.28, 0.34), yaw=rng.uniform(-0.08, 0.08))
    return m


def campfire(rng):
    m = Mesh()
    stone = m.mat(PALETTE["rock_dark"], 0.95)
    log = m.mat(PALETTE["wood_dark"], 0.9)
    flame = m.mat(PALETTE["orange"], 0.5, 0.0, 3.0)
    coal = m.mat("#a33a16", 0.9, 0.0, 1.2)
    for i in range(7):
        a = 2 * math.pi * i / 7
        blob(m, stone, (math.cos(a) * 0.45, 0.08, math.sin(a) * 0.45), 0.13,
             (1.0, 0.7, 1.0), 0, yaw=a)
    for i in range(3):
        box(m, log, (0, 0.09, 0), (0.55, 0.1, 0.11),
            yaw=i * math.pi / 3 + rng.uniform(-0.2, 0.2))
    cyl(m, coal, (0, 0.05, 0), 0.22, 0.18, 0.06, 10)
    cyl(m, flame, (0, 0.1, 0), 0.18, 0.0, 0.5, 7)
    cyl(m, flame, (0.08, 0.1, 0.05), 0.1, 0.0, 0.33, 6)
    return m


def tent(rng):
    m = Mesh()
    cloth = m.mat(rng.choice(["#3f6b45", "#7a5a3a", "#4a5f7a"]), 0.9)
    pole = m.mat(PALETTE["wood_dark"], 0.9)
    w, d, h = rng.uniform(1.5, 1.9), rng.uniform(1.4, 1.7), rng.uniform(1.1, 1.3)
    ridge_z = (d / 2) * 1.02
    for sx in (-1, 1):
        top = (0.0, h, 0.0)
        a = (sx * w / 2, 0.0, -ridge_z)
        b = (sx * w / 2, 0.0, ridge_z)
        c = (0.0, h, ridge_z)
        e = (0.0, h, -ridge_z)
        m.quad(cloth, a, b, c, e)
    for sz in (-1, 1):
        z = sz * ridge_z
        m.tri(cloth, (0.0, h, z), (-w / 2, 0.0, z), (w / 2, 0.0, z))
    for x in (-w / 2, w / 2):
        for z in (-ridge_z, ridge_z):
            box(m, pole, (x, 0.05, z), (0.05, 0.1, 0.05))
    return m


def shelf_rack(rng):
    m = Mesh()
    metal = m.mat(PALETTE["metal_dark"], 0.5, 0.7)
    wood = m.mat(PALETTE["wood"], 0.9)
    w, d, h = 1.6, 0.7, 2.0
    for sx in (-1, 1):
        for sz in (-1, 1):
            box(m, metal, (sx * (w / 2 - 0.04), h / 2, sz * (d / 2 - 0.04)),
                (0.06, h, 0.06))
    levels = rng.randint(2, 4)
    for i in range(levels):
        y = h * (i + 0.6) / (levels + 0.2)
        box(m, wood, (0, y, 0), (w - 0.1, 0.05, d - 0.08))
    return m


def car(rng):
    m = Mesh()
    body = m.mat(rng.choice([PALETTE["blue"], PALETTE["red"], PALETTE["white"],
                             PALETTE["green"], PALETTE["rust"]]), 0.5, 0.3)
    glass = m.mat(PALETTE["glass"], 0.2, 0.1)
    dark = m.mat("#2b2b2e", 0.95)
    wheel = m.mat(PALETTE["metal"], 0.5, 0.6)
    length, width = rng.uniform(3.9, 4.4), 1.75
    box(m, body, (0, 0.55, 0), (length, 0.62, width))
    box(m, body, (-0.1, 1.02, 0), (length * 0.52, 0.5, width * 0.92))
    box(m, glass, (-0.1, 1.04, 0), (length * 0.5, 0.36, width * 0.94))
    box(m, dark, (length * 0.47, 0.62, 0), (0.12, 0.22, width * 0.9))
    for sx in (-1, 1):
        for sz in (-1, 1):
            cyl(m, dark, (sx * length * 0.32, 0.34, sz * width / 2), 0.34, 0.34,
                0.22, 12, pitch=math.pi / 2)
            cyl(m, wheel, (sx * length * 0.32, 0.34, sz * width / 2 + 0.02), 0.2,
                0.2, 0.2, 10, pitch=math.pi / 2)
    return m


FAMILIES = {
    "barrel": barrel,
    "crate": crate,
    "pallet": pallet,
    "tree_pine": tree_pine,
    "tree_round": tree_round,
    "bush": bush,
    "rock": rock,
    "fence": fence,
    "street_lamp": street_lamp,
    "bench": bench,
    "dumpster": dumpster,
    "traffic_cone": traffic_cone,
    "barrier": barrier,
    "planter": planter,
    "mailbox": mailbox,
    "hydrant": hydrant,
    "ac_unit": ac_unit,
    "generator": generator,
    "table": table,
    "chair": chair,
    "sign": sign,
    "tire_stack": tire_stack,
    "sandbags": sandbags,
    "campfire": campfire,
    "tent": tent,
    "shelf_rack": shelf_rack,
    "car": car,
}


# --------------------------------------------------------------------------
# glTF binary writer (no dependencies)
# --------------------------------------------------------------------------

def _tri_normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-9:
        return (0.0, 1.0, 0.0)
    return (nx / length, ny / length, nz / length)


def write_glb(path, mesh, name):
    """Write a flat-shaded, material-only GLB. Returns the tri count."""
    buf = bytearray()
    accessors, views, prims, materials = [], [], [], []

    def add_view(data, target):
        offset = len(buf)
        buf.extend(data)
        while len(buf) % 4:
            buf.append(0)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data),
                      "target": target})
        return len(views) - 1

    for key, tris in mesh.groups.items():
        if not tris:
            continue
        r, g, b, rough, metal, emissive = key
        pos, nrm = bytearray(), bytearray()
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for tri in tris:
            n = _tri_normal(*tri)
            for v in tri:
                pos.extend(struct.pack("<3f", *v))
                nrm.extend(struct.pack("<3f", *n))
                for i in range(3):
                    lo[i] = min(lo[i], v[i])
                    hi[i] = max(hi[i], v[i])
        pview = add_view(bytes(pos), 34962)
        nview = add_view(bytes(nrm), 34962)
        accessors.append({"bufferView": pview, "componentType": 5126,
                          "count": len(tris) * 3, "type": "VEC3",
                          "min": lo, "max": hi})
        pacc = len(accessors) - 1
        accessors.append({"bufferView": nview, "componentType": 5126,
                          "count": len(tris) * 3, "type": "VEC3"})
        nacc = len(accessors) - 1

        material = {
            "name": "mat%d" % len(materials),
            "pbrMetallicRoughness": {
                "baseColorFactor": [srgb_to_linear(r), srgb_to_linear(g),
                                    srgb_to_linear(b), 1.0],
                "metallicFactor": metal,
                "roughnessFactor": rough,
            },
        }
        if emissive > 0.0:
            material["emissiveFactor"] = [
                min(1.0, srgb_to_linear(r) * emissive),
                min(1.0, srgb_to_linear(g) * emissive),
                min(1.0, srgb_to_linear(b) * emissive),
            ]
        materials.append(material)
        prims.append({"attributes": {"POSITION": pacc, "NORMAL": nacc},
                      "material": len(materials) - 1, "mode": 4})

    gltf = {
        "asset": {"version": "2.0", "generator": "propforge " + VERSION},
        "scene": 0,
        "scenes": [{"name": name, "nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{"name": name, "primitives": prims}],
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(buf)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(js) % 4:
        js += b" "
    while len(buf) % 4:
        buf.append(0)
    total = 12 + 8 + len(js) + 8 + len(buf)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A))
        fh.write(js)
        fh.write(struct.pack("<II", len(buf), 0x004E4942))
        fh.write(buf)
    return len(mesh.groups) and mesh.tris()


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def build_pack(out_dir, count, seed, families, budget=800, quiet=False):
    rng = random.Random(seed)
    names = list(families)
    if not names:
        raise SystemExit("error: no families selected")

    os.makedirs(out_dir, exist_ok=True)
    props, failures, counters = [], [], {n: 0 for n in names}

    for i in range(count):
        family = names[i % len(names)] if count >= len(names) else rng.choice(names)
        counters[family] += 1
        mesh = FAMILIES[family](rng).finish()
        tri_count = mesh.tris()
        if tri_count == 0:
            failures.append((family, "empty mesh"))
            continue
        name = "%s_%02d" % (family, counters[family])
        path = os.path.join(out_dir, name + ".glb")
        write_glb(path, mesh, name)
        lo, hi = mesh.bounds()
        size_bytes = os.path.getsize(path)
        props.append({
            "file": name + ".glb",
            "family": family,
            "tris": tri_count,
            "materials": len([k for k, v in mesh.groups.items() if v]),
            "bytes": size_bytes,
            "size": [round(hi[0] - lo[0], 3), round(hi[2] - lo[2], 3),
                     round(hi[1] - lo[1], 3)],
        })
        if not quiet:
            flag = "" if tri_count <= budget else "  <-- over budget"
            print("  %-22s %5d tris %6d B%s" % (name + ".glb", tri_count,
                                                size_bytes, flag))
        if tri_count > budget:
            failures.append((name, "%d tris > %d" % (tri_count, budget)))
        if size_bytes < 1024:
            failures.append((name, "file too small"))
        if abs(lo[1]) > 1e-4:
            failures.append((name, "does not sit on the ground"))

    manifest = {
        "generator": "propforge " + VERSION,
        "seed": seed,
        "count": len(props),
        "props": props,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return props, failures


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="propforge",
        description="Procedural low-poly game props -> GLB, zero dependencies.")
    ap.add_argument("-o", "--out", default="props", help="output directory")
    ap.add_argument("-n", "--count", type=int, default=24, help="how many props")
    ap.add_argument("-s", "--seed", type=int, default=1, help="random seed")
    ap.add_argument("-f", "--families", default="",
                    help="comma separated subset, e.g. barrel,tree_pine")
    ap.add_argument("-b", "--budget", type=int, default=800,
                    help="tri budget per prop (validation)")
    ap.add_argument("--list", action="store_true", help="list prop families")
    ap.add_argument("-q", "--quiet", action="store_true", help="no per-file output")
    ap.add_argument("--version", action="version", version="propforge " + VERSION)
    args = ap.parse_args(argv)

    if args.list:
        print("prop families (%d):" % len(FAMILIES))
        for name in FAMILIES:
            print("  " + name)
        return 0

    if args.families.strip():
        wanted = [f.strip() for f in args.families.split(",") if f.strip()]
        unknown = [f for f in wanted if f not in FAMILIES]
        if unknown:
            raise SystemExit("error: unknown families: " + ", ".join(unknown))
        families = wanted
    else:
        families = list(FAMILIES)

    print("propforge %s - %d props, seed %d -> %s" % (VERSION, args.count,
                                                      args.seed, args.out))
    props, failures = build_pack(args.out, args.count, args.seed, families,
                                 args.budget, args.quiet)
    tris = sum(p["tris"] for p in props)
    print("\n%d props, %d tris total, avg %d tris/prop"
          % (len(props), tris, tris // max(1, len(props))))
    if failures:
        print("FAIL %d issue(s):" % len(failures))
        for name, why in failures:
            print("  " + name + ": " + why)
        return 1
    print("PASS all props validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
