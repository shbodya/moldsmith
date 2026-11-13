"""Headless end-to-end test.

    blender --background --factory-startup --python tests/smoke_test.py

Runs the full operator chain on a watertight master (torus, which has an
undercut) and a non-watertight one (Suzanne), then checks that every part is
watertight, that the halves don't overlap, and that the STL files are valid.
"""

import os
import struct
import sys
import tempfile

import bmesh
import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import moldsmith  # noqa: E402
from moldsmith import geometry as geo, helpers  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def volume(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    v = bm.calc_volume(signed=False)
    bm.free()
    return v


def intersection_volume(a, b):
    tmp = geo.duplicate(a, "_tmp_isect", bpy.context.scene.collection)
    geo.apply_boolean(bpy.context, tmp, b, "INTERSECT", "MANIFOLD")
    v = volume(tmp) if not geo.is_empty(tmp) else 0.0
    helpers.remove_object(tmp)
    return v


def shifted_overlap(obj, others, offset):
    """Overlap volume between `obj` moved by `offset` and the `others`."""
    from mathutils import Matrix

    tmp = geo.duplicate(obj, "_tmp_shift", bpy.context.scene.collection)
    tmp.data.transform(Matrix.Translation(offset))
    total = sum(intersection_volume(tmp, o) for o in others)
    helpers.remove_object(tmp)
    return total


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_master(kind):
    if kind.startswith("torus"):
        bpy.ops.mesh.primitive_torus_add(major_radius=30, minor_radius=10, rotation=(1.2, 0.0, 0.3))
    else:
        bpy.ops.mesh.primitive_monkey_add(size=60)
    obj = bpy.context.active_object
    if kind == "torus_flipped":
        # Closed but inconsistently wound, as broken STL exports often are.
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.reverse_faces(bm, faces=[f for f in bm.faces if f.calc_center_median().x > 0])
        bm.to_mesh(obj.data)
        bm.free()
    if kind == "torus_mirrored":
        obj.scale = (-1.0, 1.0, 1.0)
    obj.location = (5.0, -3.0, 40.0)
    bpy.context.view_layer.update()
    return obj


def run_case(kind, axis, key_shape):
    print(f"\n== {kind}, split {axis}, {key_shape} keys ==")
    reset_scene()
    master = make_master(kind)
    verts_before = len(master.data.vertices)
    matrix_before = master.matrix_world.copy()

    s = bpy.context.scene.moldsmith
    s.parting_axis = axis
    s.key_shape = key_shape
    check(bpy.ops.moldsmith.setup() == {"FINISHED"}, "setup finished")
    check(len(helpers.objects_with_role(bpy.context.scene, helpers.ROLE_POUR)) == 1, "one pour marker")
    check(bool(helpers.objects_with_role(bpy.context.scene, helpers.ROLE_PARTING)), "parting preview exists")

    check(bpy.ops.moldsmith.generate() == {"FINISHED"}, "generate finished")
    parts = {o.name: o for o in helpers.objects_with_role(bpy.context.scene, helpers.ROLE_PART)}
    print("  parts:", sorted(parts))
    for name in ("Mold_A", "Mold_B", "Casting_Box_1", "Casting_Box_2", "Pour_Rods"):
        check(name in parts, f"{name} generated")

    deps = bpy.context.evaluated_depsgraph_get()
    for name, obj in sorted(parts.items()):
        r = geo.manifold_report(obj, deps)
        check(r["is_watertight"], f"{name} watertight ({r['faces']} faces, {r['non_manifold_edges']} bad edges)")

    if "Mold_A" in parts and "Mold_B" in parts:
        a, b = parts["Mold_A"], parts["Mold_B"]
        lo, hi = helpers.mold_bounds(s, bpy.context.scene)
        block = (hi - lo).x * (hi - lo).y * (hi - lo).z
        overlap = intersection_volume(a, b)
        check(overlap < block * 1e-5, f"halves do not overlap (overlap {overlap:.3f} of block {block:.0f})")
        carved = volume(a) + volume(b)
        check(carved < block - volume(master) * 0.9, "master cavity removed from the block")
        check(carved > block * 0.3, "halves keep most of the block")

    check(len(master.data.vertices) == verts_before, "master mesh untouched")
    check(master.matrix_world == matrix_before, "master transform untouched")

    s.explode = 20.0
    check(abs(parts["Mold_A"].location.length - 20.0) < 1e-4, "explode moves Mold_A")

    out = tempfile.mkdtemp(prefix="moldsmith_")
    s.export_dir = out + os.sep
    check(bpy.ops.moldsmith.export() == {"FINISHED"}, "export finished")
    files = sorted(os.listdir(out))
    check(len(files) == len(parts), f"one STL per part ({files})")
    for f in files:
        path = os.path.join(out, f)
        with open(path, "rb") as fh:
            fh.seek(80)
            (n,) = struct.unpack("<I", fh.read(4))
        check(os.path.getsize(path) == 84 + 50 * n and n > 0, f"{f} valid binary STL ({n} triangles)")

    check(bpy.ops.moldsmith.clear() == {"FINISHED"}, "clear finished")
    check(not helpers.objects_with_role(bpy.context.scene, helpers.ROLE_PART), "parts removed")
    leftovers = [c.name for c in bpy.data.collections if c.name.startswith("_ms")]
    check(not leftovers, f"no temporary collections left {leftovers}")


def make_cup(chamfered=False):
    """Open cup, 80 mm across, 5 mm floor, raised 'logo' on the side, off origin.

    `chamfered` gives it a 45-degree chamfer on the rim and on the foot, so
    neither the top nor the bottom of its hull is a flat ring of radius 40.
    """
    if chamfered:
        bpy.ops.mesh.primitive_cylinder_add(radius=40, depth=60, vertices=96, location=(10, -5, 55))
        cup = bpy.context.active_object
        for z0, r0, r1 in ((85.0, 40.0, 37.0), (20.0, 37.0, 40.0)):
            bpy.ops.mesh.primitive_cone_add(radius1=r0, radius2=r1, depth=5.0, vertices=96, location=(10, -5, z0 + 2.5))
            ring = bpy.context.active_object
            geo.apply_boolean(bpy.context, cup, ring, "UNION", "MANIFOLD")
            helpers.remove_object(ring)
    else:
        bpy.ops.mesh.primitive_cylinder_add(radius=40, depth=70, vertices=96, location=(10, -5, 55))
        cup = bpy.context.active_object
    cup.name = "Cup"
    bpy.ops.mesh.primitive_cylinder_add(radius=35, depth=70, vertices=96, location=(10, -5, 60))
    inner = bpy.context.active_object
    bpy.ops.mesh.primitive_cube_add(size=1, location=(10, -45, 55), scale=(30, 3, 20))
    logo = bpy.context.active_object
    geo.apply_boolean(bpy.context, cup, inner, "DIFFERENCE", "MANIFOLD")
    geo.apply_boolean(bpy.context, cup, logo, "UNION", "MANIFOLD")
    helpers.remove_object(inner)
    helpers.remove_object(logo)
    bpy.context.view_layer.objects.active = cup
    cup.select_set(True)
    bpy.context.view_layer.update()
    return cup


def run_vessel_case(split, recess, chamfered=False):
    print(f"\n== vessel cup, split {split}, recess {recess} mm{', chamfered rim and foot' if chamfered else ''} ==")
    reset_scene()
    master = make_cup(chamfered)
    verts_before = len(master.data.vertices)
    s = bpy.context.scene.moldsmith
    s.mold_type = "VESSEL"
    check(bpy.ops.moldsmith.setup() == {"FINISHED"}, "setup finished")
    check(not helpers.objects_with_role(bpy.context.scene, helpers.ROLE_POUR), "no pour markers in vessel mode")
    s.vessel_split = split
    s.recess_depth = recess
    check(bpy.ops.moldsmith.generate() == {"FINISHED"}, "generate finished")

    parts = {o.name: o for o in helpers.objects_with_role(bpy.context.scene, helpers.ROLE_PART)}
    print("  parts:", sorted(parts))
    expected = ("Shell_1", "Shell_2", "Rail_1", "Rail_2", "Pin_1", "Pin_2", "Base", "Core")
    for name in expected:
        check(name in parts, f"{name} generated")
    if not all(name in parts for name in expected):
        return

    deps = bpy.context.evaluated_depsgraph_get()
    for name, obj in sorted(parts.items()):
        r = geo.manifold_report(obj, deps)
        check(r["is_watertight"], f"{name} watertight ({r['faces']} faces)")

    world_master = geo.copy_world_mesh(master, "_tmp_master", bpy.context.scene.collection, deps)
    pairs = [
        ("Core", world_master), ("Shell_1", world_master), ("Shell_2", world_master), ("Base", world_master),
        ("Shell_1", parts["Core"]), ("Shell_2", parts["Core"]), ("Shell_1", parts["Shell_2"]),
        ("Rail_1", parts["Shell_1"]), ("Rail_1", parts["Shell_2"]), ("Rail_2", parts["Shell_1"]),
        ("Rail_2", parts["Shell_2"]), ("Base", parts["Shell_1"]), ("Base", parts["Shell_2"]),
        ("Rail_1", parts["Base"]), ("Base", parts["Core"]),
        ("Pin_1", parts["Shell_1"]), ("Pin_1", parts["Shell_2"]), ("Pin_2", parts["Shell_1"]),
        ("Pin_2", parts["Shell_2"]), ("Pin_1", parts["Rail_1"]), ("Pin_2", parts["Rail_2"]),
        ("Core", parts["Rail_1"]), ("Core", parts["Rail_2"]),
        ("Pin_1", parts["Core"]), ("Pin_2", parts["Core"]),
    ]
    for a, b in pairs:
        v = intersection_volume(parts[a], b)
        check(v < 1.0, f"{a} does not overlap {b.name.lstrip('_tmp_') or b.name} ({v:.3f} mm3)")

    # The connections must actually hold: nudge each part 1.5 mm and it collides.
    from mathutils import Vector

    shells = [parts["Shell_1"], parts["Shell_2"]]
    ax = 0 if split == "X" else 1
    ay = 1 - ax
    for name, side in (("Rail_1", 1), ("Rail_2", -1)):
        out_vec = Vector((0.0, 0.0, 0.0))
        out_vec[ay] = side * 1.5
        check(shifted_overlap(parts[name], shells, out_vec) > 1.0, f"{name} cannot pull off the seam sideways")
    for name in ("Pin_1", "Pin_2"):
        check(shifted_overlap(parts[name], shells, Vector((0.0, 0.0, -1.5))) > 0.1, f"{name} rests on its bore floor")
        for axis in (ax, ay):
            v = Vector((0.0, 0.0, 0.0))
            v[axis] = 1.5
            check(shifted_overlap(parts[name], shells, v) > 0.1, f"{name} is held in its bore ({'XY'[axis]})")
    for axis in (ax, ay):
        for sign in (1, -1):
            v = Vector((0.0, 0.0, 0.0))
            v[axis] = sign * 1.5
            check(shifted_overlap(parts["Core"], shells, v) > 1.0, f"core is located by the saddles ({'+' if sign > 0 else '-'}{'XY'[axis]})")
    check(shifted_overlap(parts["Core"], shells, Vector((0.0, 0.0, 1.0))) < 1.0, "core lifts straight out")
    check(shifted_overlap(parts["Shell_1"], [parts["Shell_2"]], Vector((0.0, 0.0, 0.0))) < 1.0, "halves meet without overlap")

    mm = helpers.mm_per_unit(bpy.context.scene)
    core = geo.mesh_coords(parts["Core"])
    floor_z = 25.0  # inside floor of the cup (bottom at z=20, 5 mm floor)
    gap_floor = (core[:, 2].min() - floor_z) * mm
    check(abs(gap_floor - s.vessel_inner) < 1.0, f"inner silicone under the core {gap_floor:.2f} mm (want {s.vessel_inner:.2f})")
    core_body = core[core[:, 2] < master.matrix_world.translation.z]
    radial = np.sqrt((core_body[:, 0] - 10.0) ** 2 + (core_body[:, 1] + 5.0) ** 2).max()
    gap_side = (35.0 - radial) * mm
    check(abs(gap_side - s.vessel_inner) < 1.0, f"inner silicone beside the core {gap_side:.2f} mm (want {s.vessel_inner:.2f})")

    shell = np.vstack([geo.mesh_coords(parts["Shell_1"]), geo.mesh_coords(parts["Shell_2"])])
    # The shell must never lean in over the master: at every height its wall
    # stays Outer Silicone away from the widest point of the cup.
    radial_shell = np.sqrt((shell[:, 0] - 10.0) ** 2 + (shell[:, 1] + 5.0) ** 2)
    inner_min = radial_shell.min() * mm
    check(inner_min > 40.0 + s.vessel_wall - 0.1, f"shell wall never leans in ({inner_min:.2f} mm from axis, want >= {40.0 + s.vessel_wall:.2f})")
    check(shell[:, 2].max() > master.matrix_world.translation.z + 35.0 + s.vessel_top, "shell rim above the pour level")
    check(abs(shell[:, 2].min() - (20.0 + recess)) < 1e-3, "shell stands on the base top")

    silicone = geo.convex_offset_object("_tmp_sil", geo.mesh_coords(world_master), s.vessel_wall, bpy.context.scene.collection)
    geo.apply_boolean(bpy.context, silicone, world_master, "DIFFERENCE", "MANIFOLD")
    geo.apply_boolean(bpy.context, silicone, parts["Core"], "DIFFERENCE", "MANIFOLD")
    check(geo.mesh_volume(silicone) > 0.0, f"silicone volume {geo.mesh_volume(silicone) / 1000:.0f} cm3")
    helpers.remove_object(silicone)
    helpers.remove_object(world_master)

    check(len(master.data.vertices) == verts_before, "master mesh untouched")
    s.explode = 30.0
    check(parts["Core"].location.z > 0 and parts["Base"].location.z < 0, "explode separates core and base")

    out = tempfile.mkdtemp(prefix="moldsmith_vessel_")
    s.export_dir = out + os.sep
    check(bpy.ops.moldsmith.export() == {"FINISHED"}, "export finished")
    check(len(os.listdir(out)) == len(parts), "one STL per part")

    check(bpy.ops.moldsmith.clear() == {"FINISHED"}, "clear finished")
    check(not [g for g in bpy.data.node_groups], "no node groups left")
    check(not [c.name for c in bpy.data.collections if c.name.startswith("_ms")], "no temporary collections left")


def run_vessel_rejects_closed_solid():
    print("\n== vessel mode on a closed sphere ==")
    reset_scene()
    bpy.ops.mesh.primitive_uv_sphere_add(radius=30, location=(0, 0, 40))
    s = bpy.context.scene.moldsmith
    s.mold_type = "VESSEL"
    bpy.ops.moldsmith.setup()
    try:
        result = bpy.ops.moldsmith.generate()
    except RuntimeError as exc:
        result = {"CANCELLED"}
        print("  ", str(exc).strip().splitlines()[-1])
    check(result == {"CANCELLED"}, "generate refuses a solid with no opening")
    check(not helpers.objects_with_role(bpy.context.scene, helpers.ROLE_PART), "no parts left behind")


moldsmith.register()
moldsmith.unregister()
moldsmith.register()
run_case("torus", "Z", "SPHERE")
run_case("torus_flipped", "Z", "SPHERE")
run_case("torus_mirrored", "X", "CONE")
run_case("torus", "Y", "CONE")
run_case("monkey", "X", "SPHERE")
run_vessel_case("X", 0.0)
run_vessel_case("Y", 0.6)
run_vessel_case("X", 0.0, chamfered=True)
run_vessel_rejects_closed_solid()

print("\nRESULT:", "FAIL" if failures else "PASS", f"({len(failures)} failure(s))")
for f in failures:
    print("  -", f)
sys.exit(1 if failures else 0)
