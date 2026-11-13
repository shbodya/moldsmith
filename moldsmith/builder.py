"""Builds the mold parts.

Layout, with the parting plane perpendicular to the split axis:

    Mold_A   block side above the plane (+axis), with key sockets.
    Mold_B   block side below the plane (-axis), with key knobs.
             Printed rigid, B also serves as the parting bed for the first
             silicone pour: silicone poured onto it inside the casting box
             becomes the silicone A half, sockets and all.
    Casting_Box   printable box with an open +axis side that holds the bed.
    Pour_Rods     printable sprue and vent rods that sit on the master while
                  silicone is poured, leaving the channels behind.

All length settings are in millimetres and converted via helpers.mm().
"""

import bpy
from mathutils import Vector

from . import geometry as geo
from . import helpers

PART_COLORS = {
    "Mold_A": (0.85, 0.35, 0.25, 1.0),
    "Mold_B": (0.25, 0.55, 0.85, 1.0),
    "Casting_Box": (0.75, 0.75, 0.72, 1.0),
    "Pour_Rods": (0.95, 0.80, 0.20, 1.0),
    "Shell": (0.62, 0.55, 0.25, 1.0),
    "Rail": (0.35, 0.75, 0.40, 1.0),
    "Base": (0.35, 0.75, 0.40, 1.0),
    "Core": (0.70, 0.15, 0.15, 1.0),
    "Pin": (0.25, 0.65, 0.80, 1.0),
}


class BuildError(Exception):
    pass


def refresh_master_bounds(context, settings, report=None):
    depsgraph = context.evaluated_depsgraph_get()
    flipped = bool(report and report["flipped_edges"])
    co, nrm, edges = geo.evaluated_arrays(settings.master, depsgraph, fix_winding=flipped)
    if len(co) == 0:
        raise BuildError("The master mesh has no vertices")
    settings.master_min = co.min(axis=0)
    settings.master_max = co.max(axis=0)
    return co, nrm, edges


def master_size_mm(settings, scene):
    size = Vector(settings.master_max) - Vector(settings.master_min)
    return max(size) * helpers.mm_per_unit(scene)


def auto_size(settings, scene):
    """Scale the defaults to the master so a first build is usually printable."""
    d = master_size_mm(settings, scene)

    def clamp(x, lo, hi):
        return max(lo, min(hi, x))

    settings.padding = clamp(0.12 * d, 5.0, 40.0)
    settings.key_radius = min(clamp(0.035 * d, 2.0, 10.0), 0.4 * settings.padding)
    settings.sprue_radius = clamp(0.025 * d, 2.0, 6.0)
    settings.funnel_radius = settings.sprue_radius * 2.5
    settings.funnel_depth = settings.funnel_radius
    settings.vent_radius = clamp(0.008 * d, 0.75, 2.0)
    settings.voxel_size = clamp(d / 400.0, 0.1, 1.0)


def choose_pour_point(settings, scene, co, nrm):
    """Highest up-facing point; near the parting plane when the plane is vertical,
    so the sprue is split between both halves."""
    axis = geo.AXIS_INDEX[settings.parting_axis]
    if axis != 2:
        c = helpers.parting_coordinate(settings, scene)
        band = max(helpers.mm(scene, settings.sprue_radius), 0.02 * (settings.master_max[axis] - settings.master_min[axis]))
        near = abs(co[:, axis] - c) < band
        if near.any():
            return geo.pour_point(co[near], nrm[near])
    return geo.pour_point(co, nrm)


def place_auto_vents(settings, scene, co, nrm, edges):
    helpers.clear_markers(scene, helpers.ROLE_VENT)
    pours = [m.matrix_world.translation.copy() for m in helpers.objects_with_role(scene, helpers.ROLE_POUR)]
    size = max(Vector(settings.master_max) - Vector(settings.master_min))
    points = geo.air_trap_points(
        co, nrm, edges,
        exclude=pours,
        min_separation=0.15 * size,
        max_count=settings.vent_count,
    )
    marker_size = helpers.mm(scene, settings.vent_radius) * 4.0
    for p in points:
        helpers.add_marker(scene, helpers.ROLE_VENT, p, marker_size)
    return len(points)


# ---------------------------------------------------------------------------
# Shared build infrastructure
# ---------------------------------------------------------------------------

class Workspace:
    """Temporary collections for a build; everything in them is deleted on exit."""

    def __init__(self, context, steps):
        self.context = context
        self.scene = context.scene
        self.steps = steps
        self.collections = []

    def __enter__(self):
        helpers.remove_collection(helpers.OUTPUT_COLLECTION)
        helpers.remove_collection(helpers.WORK_COLLECTION)
        self.work = helpers.ensure_collection(self.scene, helpers.WORK_COLLECTION)
        self.collections.append(self.work)
        self.context.window_manager.progress_begin(0, self.steps)
        return self

    def sub(self, name):
        coll = bpy.data.collections.new(name)
        self.work.children.link(coll)
        self.collections.append(coll)
        return coll

    def progress(self, step):
        self.context.window_manager.progress_update(step)

    def publish(self, parts):
        """Move finished (object, explode_direction) pairs into the output collection."""
        for obj, _direction in parts:
            if geo.is_empty(obj):
                raise BuildError(f"{obj.name} came out empty; check the master and the settings")
        out = helpers.ensure_collection(self.scene, helpers.OUTPUT_COLLECTION, hide_render=False)
        for obj, direction in parts:
            for coll in list(obj.users_collection):
                coll.objects.unlink(obj)
            out.objects.link(obj)
            obj[helpers.ROLE_KEY] = helpers.ROLE_PART
            obj[helpers.EXPLODE_KEY] = tuple(direction)
            kind = next((k for k in PART_COLORS if obj.name.startswith(k)), None)
            if kind:
                obj.data.materials.clear()
                obj.data.materials.append(_material(f"MS_{kind}", PART_COLORS[kind]))
        return [obj for obj, _direction in parts]

    def __exit__(self, *exc):
        for coll in reversed(self.collections):
            helpers.remove_collection(coll)
        self.context.window_manager.progress_end()
        return False


def axis_vector(axis, sign=1.0):
    v = Vector((0.0, 0.0, 0.0))
    v[axis] = sign
    return v


def prepare_cavity(context, s, collection, warnings):
    """World-space copy of the master with consistent winding, repaired if needed.

    Returns (cavity_object, solver) where solver is what later booleans
    against the cavity should use.
    """
    scene = context.scene
    cavity = geo.copy_world_mesh(s.master, "_ms_cavity", collection, context.evaluated_depsgraph_get())
    geo.recalc_normals(cavity)
    report = geo.manifold_report(cavity, context.evaluated_depsgraph_get())
    repair = not report["is_watertight"] and s.voxel_repair
    solver = s.solver
    if solver == "AUTO":
        solver = "MANIFOLD" if report["is_watertight"] or repair else "EXACT"
    if not report["is_watertight"] and not repair:
        warnings.append(
            f"Master is not watertight ({report['non_manifold_edges']} bad edges); "
            "the parts may not be printable. Enable Repair Master"
        )
    if repair:
        geo.apply_voxel_remesh(context, cavity, helpers.mm(scene, s.voxel_size))
        fixed = geo.manifold_report(cavity, context.evaluated_depsgraph_get())
        if not fixed["is_watertight"]:
            raise BuildError("Voxel repair did not close the master; try a smaller voxel size")
        warnings.append(
            f"Master was not watertight ({report['non_manifold_edges']} bad edges); "
            f"cavity rebuilt with {s.voxel_size:.2f} mm voxels"
        )
    return cavity, solver


# ---------------------------------------------------------------------------
# Block mold
# ---------------------------------------------------------------------------

def _material(name, color):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def _halfspace(lo, hi, axis, c, positive, margin):
    lo = lo - Vector((margin, margin, margin))
    hi = hi + Vector((margin, margin, margin))
    if positive:
        lo[axis] = c
    else:
        hi[axis] = c
    return geo.box_bmesh(lo, hi)


def _channel_bmeshes(settings, scene, top_z, margin):
    """Sprue + funnel for each pour marker and a straight vent for each vent marker."""
    up = Vector((0.0, 0.0, 1.0))
    embed = helpers.mm(scene, settings.channel_embed)
    sprue_r = helpers.mm(scene, settings.sprue_radius)
    funnel_r = max(helpers.mm(scene, settings.funnel_radius), sprue_r)
    vent_r = helpers.mm(scene, settings.vent_radius)
    out = []

    for marker in helpers.objects_with_role(scene, helpers.ROLE_POUR):
        p = marker.matrix_world.translation.copy()
        start = p - up * embed
        if start.z >= top_z:
            raise BuildError(f"{marker.name} is above the top of the mold")
        depth = min(helpers.mm(scene, settings.funnel_depth), (top_z - p.z) * 0.8)
        if depth <= 0.0 or funnel_r <= sprue_r:
            out.append(geo.frustum_bmesh(start, Vector((p.x, p.y, top_z + margin)), sprue_r, sprue_r))
            continue
        neck = Vector((p.x, p.y, top_z - depth))
        overlap = up * min(depth * 0.25, sprue_r)
        out.append(geo.frustum_bmesh(start, neck + overlap, sprue_r, sprue_r))
        # Keep the funnel slope past the top face so it cuts a clean opening.
        flare = funnel_r + (funnel_r - sprue_r) * margin / depth
        out.append(geo.frustum_bmesh(neck, Vector((p.x, p.y, top_z + margin)), sprue_r, flare))

    for marker in helpers.objects_with_role(scene, helpers.ROLE_VENT):
        p = marker.matrix_world.translation.copy()
        start = p - up * embed
        if start.z >= top_z:
            raise BuildError(f"{marker.name} is above the top of the mold")
        out.append(geo.frustum_bmesh(start, Vector((p.x, p.y, top_z + margin)), vent_r, vent_r))
    return out


def _key_centers(lo, hi, axis, c, inset, count):
    u, v = [i for i in range(3) if i != axis]
    uv = [
        (lo[u] + inset, lo[v] + inset),
        (hi[u] - inset, hi[v] - inset),
        (hi[u] - inset, lo[v] + inset),
        (lo[u] + inset, hi[v] - inset),
    ][:count]
    centers = []
    for a, b in uv:
        p = Vector((0.0, 0.0, 0.0))
        p[axis], p[u], p[v] = c, a, b
        centers.append(p)
    return centers


def _key_bmesh(shape, center, axis, radius, grow):
    """Knob on B that sticks up into A. `grow` enlarges it for the A socket."""
    if shape == "SPHERE":
        return geo.sphere_bmesh(center, radius + grow)
    n = Vector((0.0, 0.0, 0.0))
    n[axis] = 1.0
    height = radius
    tip = radius * 0.3
    slope = (radius - tip) / height
    below = radius * 0.5  # buried part, keeps the base off the parting face
    base = center - n * below
    top = center + n * (height + grow)
    return geo.frustum_bmesh(base, top, radius + grow + slope * below, tip + grow)


def build(context):
    scene = context.scene
    s = scene.moldsmith
    if s.master is None:
        raise BuildError("Pick a master object first")

    warnings = []
    co, _nrm, _edges = refresh_master_bounds(context, s)
    del co, _nrm, _edges

    axis = geo.AXIS_INDEX[s.parting_axis]
    lo, hi = helpers.mold_bounds(s, scene)
    c = helpers.parting_coordinate(s, scene)
    if not (s.master_min[axis] < c < s.master_max[axis]):
        raise BuildError("The parting plane does not cross the master; reduce the offset")
    pad = helpers.mm(scene, s.padding)
    margin = pad

    if not helpers.objects_with_role(scene, helpers.ROLE_POUR):
        warnings.append("No pour marker: the mold has no sprue")

    with Workspace(context, 8) as ws:
        work = ws.work
        voids = ws.sub("_ms_voids")
        channels = ws.sub("_ms_channels")
        knobs = ws.sub("_ms_knobs")
        sockets = ws.sub("_ms_sockets")

        cavity, solver = prepare_cavity(context, s, voids, warnings)

        for i, bm in enumerate(_channel_bmeshes(s, scene, hi.z, margin)):
            ch = geo.bmesh_to_object(f"_ms_channel_{i}", bm, voids)
            channels.objects.link(ch)

        key_r = helpers.mm(scene, s.key_radius)
        inset = pad * 0.5
        if key_r > inset * 0.9:
            key_r = inset * 0.9
            warnings.append(
                f"Key radius reduced to {key_r * helpers.mm_per_unit(scene):.2f} mm to fit inside the mold wall"
            )
        clearance = helpers.mm(scene, s.key_clearance)
        for i, center in enumerate(_key_centers(lo, hi, axis, c, inset, int(s.key_count))):
            geo.bmesh_to_object(f"_ms_knob_{i}", _key_bmesh(s.key_shape, center, axis, key_r, 0.0), knobs)
            geo.bmesh_to_object(f"_ms_socket_{i}", _key_bmesh(s.key_shape, center, axis, key_r, clearance), sockets)
        ws.progress(1)

        # The heavy boolean, done once: block minus master and channels.
        carved = geo.bmesh_to_object("_ms_carved", geo.box_bmesh(lo, hi), work)
        block_volume = geo.mesh_volume(carved)
        geo.apply_boolean(context, carved, voids, "DIFFERENCE", solver)
        # A refused boolean returns the input unchanged rather than failing loudly.
        if geo.is_empty(carved) or geo.mesh_volume(carved) > block_volume - 0.5 * geo.mesh_volume(cavity):
            raise BuildError(
                "Subtracting the master failed; enable Repair Master, or fix the mesh "
                "(Mesh > Clean Up, Recalculate Normals)"
            )
        ws.progress(3)

        half_pos = geo.bmesh_to_object("_ms_half_pos", _halfspace(lo, hi, axis, c, True, margin), work)
        half_neg = geo.bmesh_to_object("_ms_half_neg", _halfspace(lo, hi, axis, c, False, margin), work)

        part_a = geo.duplicate(carved, "Mold_A", work)
        geo.apply_boolean(context, part_a, half_pos, "INTERSECT", solver)
        geo.apply_boolean(context, part_a, sockets, "DIFFERENCE", solver)
        ws.progress(4)

        part_b = geo.duplicate(carved, "Mold_B", work)
        geo.apply_boolean(context, part_b, half_neg, "INTERSECT", solver)
        geo.apply_boolean(context, part_b, knobs, "UNION", solver)
        ws.progress(5)

        parts = [(part_a, axis_vector(axis, 1.0)), (part_b, axis_vector(axis, -1.0))]
        if s.make_casting_kit:
            parts += [(obj, Vector()) for obj in _casting_kit(context, s, scene, lo, hi, axis, cavity, channels, work, solver)]
        ws.progress(7)
        published = ws.publish(parts)

    helpers.apply_explode(scene)
    return published, warnings


def _casting_kit(context, s, scene, lo, hi, axis, cavity, channels, work, solver):
    parts = []
    gap = helpers.mm(scene, s.box_clearance)
    wall = helpers.mm(scene, s.box_wall)

    inner_lo = lo - Vector((gap, gap, gap))
    inner_hi = hi + Vector((gap, gap, gap))
    outer_lo = inner_lo - Vector((wall, wall, wall))
    outer_hi = inner_hi + Vector((wall, wall, wall))
    # Open on the +axis side, rim flush with the top of the silicone.
    outer_hi[axis] = hi[axis]
    inner_hi[axis] = hi[axis] + wall * 2.0

    box = geo.bmesh_to_object("Casting_Box", geo.box_bmesh(outer_lo, outer_hi), work)
    cutter = geo.bmesh_to_object("_ms_box_inner", geo.box_bmesh(inner_lo, inner_hi), work)
    geo.apply_boolean(context, box, cutter, "DIFFERENCE", "MANIFOLD")

    if s.split_box:
        u = [i for i in range(3) if i != axis][0]
        mid = (lo[u] + hi[u]) / 2.0
        for positive, suffix in ((True, "1"), (False, "2")):
            half = geo.duplicate(box, f"Casting_Box_{suffix}", work)
            cut = geo.bmesh_to_object(
                f"_ms_box_half_{suffix}", _halfspace(outer_lo, outer_hi, u, mid, positive, wall), work
            )
            geo.apply_boolean(context, half, cut, "INTERSECT", "MANIFOLD")
            parts.append(half)
        helpers.remove_object(box)
    else:
        parts.append(box)

    channel_objs = list(channels.objects)
    if channel_objs:
        rods = geo.duplicate(channel_objs[0], "Pour_Rods", work)
        if len(channel_objs) > 1:
            rest = bpy.data.collections.new("_ms_rods_rest")
            work.children.link(rest)
            for obj in channel_objs[1:]:
                rest.objects.link(obj)
            geo.apply_boolean(context, rods, rest, "UNION", "MANIFOLD")
            bpy.data.collections.remove(rest)
        clip = geo.bmesh_to_object("_ms_rod_clip", geo.box_bmesh(lo, hi), work)
        geo.apply_boolean(context, rods, clip, "INTERSECT", "MANIFOLD")
        geo.apply_boolean(context, rods, cavity, "DIFFERENCE", solver)
        if not geo.is_empty(rods):
            parts.append(rods)
    return parts
