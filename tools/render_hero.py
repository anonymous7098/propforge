"""
Render a contact sheet of every GLB in a prop pack (Blender, headless).

    blender.exe --background --factory-startup --python tools/render_hero.py -- \
        --props demo/props --out docs/hero.png --cols 7

This is a build-time tool only: propforge itself needs no Blender.
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv
argv = argv[argv.index("--") + 1:] if "--" in argv else []

ap = argparse.ArgumentParser()
ap.add_argument("--props", default="demo/props")
ap.add_argument("--out", default="docs/hero.png")
ap.add_argument("--cols", type=int, default=7)
ap.add_argument("--res", type=int, default=1100)
ap.add_argument("--samples", type=int, default=64)
ap.add_argument("--azimuth", type=float, default=0.0)
ap.add_argument("--elevation", type=float, default=42.0)
args = ap.parse_args(argv)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def add_ground(size):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    plane = bpy.context.object
    mat = bpy.data.materials.new("ground")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.48, 0.48, 0.46, 1)
    bsdf.inputs["Roughness"].default_value = 0.95
    plane.data.materials.append(mat)
    return plane


def add_lights(center, radius):
    bpy.ops.object.light_add(type="SUN", location=(center[0] - 6, center[1] - 8, 12))
    sun = bpy.context.object
    sun.data.energy = 3.0
    sun.data.angle = math.radians(8)
    sun.rotation_euler = (math.radians(48), 0, math.radians(34))

    bpy.ops.object.light_add(type="SUN", location=(center[0] + 6, center[1] - 4, 7))
    fill = bpy.context.object
    fill.data.energy = 1.6
    fill.data.angle = math.radians(30)
    fill.rotation_euler = (math.radians(62), 0, math.radians(115))


def main():
    reset()
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"

    files = sorted(f for f in os.listdir(args.props) if f.endswith(".glb"))
    if not files:
        raise SystemExit("no .glb files in " + args.props)

    objects = []
    for name in files:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=os.path.join(args.props, name))
        new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
        for o in new:
            objects.append(o)

    # footprint of every prop so the grid never overlaps
    # row packing by real footprint, then a tight ortho fit
    gap = 0.8
    rows = []
    row, row_w = [], 0.0
    limit = 15.0
    for o in objects:
        w = max(o.dimensions.x, 0.4)
        if row and row_w + w + gap > limit:
            rows.append(row)
            row, row_w = [], 0.0
        row.append(o)
        row_w += w + gap
    if row:
        rows.append(row)

    cell = 0.0
    for o in objects:
        o.select_set(False)

    y = 0.0
    for row in reversed(rows):
        depth = max(o.dimensions.y for o in row)
        total = sum(max(o.dimensions.x, 0.4) for o in row) + gap * (len(row) - 1)
        x = -total / 2.0
        for o in row:
            w = max(o.dimensions.x, 0.4)
            o.location = (x + w / 2.0, y + depth / 2.0, 0.0)
            x += w + gap
        y += depth + gap * 3.4

    # scene bounds in world space
    bpy.context.view_layer.update()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objects:
        for corner in o.bound_box:
            p = o.matrix_world @ Vector(corner)
            lo = Vector((min(lo.x, p.x), min(lo.y, p.y), min(lo.z, p.z)))
            hi = Vector((max(hi.x, p.x), max(hi.y, p.y), max(hi.z, p.z)))
    center = (lo + hi) / 2.0
    radius = max(hi.x - lo.x, hi.y - lo.y)

    add_ground(max(hi.x - lo.x, hi.y - lo.y) * 12.0)
    add_lights(center, radius)

    az = math.radians(args.azimuth)
    el = math.radians(args.elevation)
    dist = radius * 3.0
    cam_loc = Vector((math.sin(az) * math.cos(el) * dist,
                      -math.cos(az) * math.cos(el) * dist,
                      math.sin(el) * dist)) + center
    bpy.ops.object.camera_add(location=cam_loc)
    cam = bpy.context.object
    direction = center - cam_loc
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam.data.type = "ORTHO"
    cam.data.clip_start = 0.05
    cam.data.clip_end = 4000.0

    # fit the ortho frame to the projected corners
    aspect = args.res / float(int(args.res * 0.56))
    rot = cam.rotation_euler.to_matrix()
    half_w = half_h = 0.0
    for x in (lo.x, hi.x):
        for y in (lo.y, hi.y):
            for z in (lo.z, hi.z):
                local = rot.transposed() @ (Vector((x, y, z)) - cam_loc)
                half_w = max(half_w, abs(local.x))
                half_h = max(half_h, abs(local.y))
    cam.data.ortho_scale = max(half_w * 2.0, half_h * 2.0 * aspect) * 1.02#print('DEBUG bbox', tuple(round(v,2) for v in lo), tuple(round(v,2) for v in hi), 'ortho', round(cam.data.ortho_scale,2), 'halfw', round(half_w,2), 'halfh', round(half_h,2))
    scene.camera = cam

    scene.render.resolution_x = args.res
    scene.render.resolution_y = int(args.res * 0.56)
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.eevee.taa_render_samples = args.samples

    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.24, 0.28, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.35
    scene.world = world

    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    scene.render.filepath = os.path.abspath(args.out)
    bpy.ops.render.render(write_still=True)
    print("rendered %d props -> %s" % (len(objects), args.out))


main()




