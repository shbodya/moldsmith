"""Scene bookkeeping: units, collections, markers and the parting-plane preview."""

import bpy
from mathutils import Vector

from .geometry import AXIS_INDEX

ROLE_KEY = "moldsmith_role"
EXPLODE_KEY = "moldsmith_explode"
HELPER_COLLECTION = "Moldsmith Helpers"
OUTPUT_COLLECTION = "Moldsmith Parts"
WORK_COLLECTION = "_moldsmith_work"

ROLE_POUR = "POUR"
ROLE_VENT = "VENT"
ROLE_PARTING = "PARTING"
ROLE_PART = "PART"


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def mm_per_unit(scene):
    """Millimetres per Blender unit.

    STL files carry bare numbers that slicers read as millimetres, and Blender
    imports them 1:1 into a metre scene. So a unit scale of 1.0 is taken to mean
    1 unit = 1 mm. Any other unit scale (0.001 for mm, 0.01 for cm, ...) is
    honoured as set.
    """
    scale = scene.unit_settings.scale_length
    if abs(scale - 1.0) < 1e-9:
        return 1.0
    return scale * 1000.0


def mm(scene, value_mm):
    """Convert millimetres to Blender units."""
    return value_mm / mm_per_unit(scene)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

def ensure_collection(scene, name, hide_render=True):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        coll.hide_render = hide_render
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    return coll


def remove_collection(coll):
    """Remove a collection (or collection name) and the objects in it."""
    if isinstance(coll, str):
        coll = bpy.data.collections.get(coll)
    if coll is None:
        return
    for obj in list(coll.objects):
        remove_object(obj)
    bpy.data.collections.remove(coll)


def remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if isinstance(data, bpy.types.Mesh) and data.users == 0:
        bpy.data.meshes.remove(data)


def objects_with_role(scene, role):
    return [o for o in scene.objects if o.get(ROLE_KEY) == role]


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def add_marker(scene, role, location, size):
    coll = ensure_collection(scene, HELPER_COLLECTION)
    name = "MS_Pour" if role == ROLE_POUR else "MS_Vent"
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "SPHERE" if role == ROLE_POUR else "SINGLE_ARROW"
    empty.empty_display_size = size
    empty.location = location
    empty[ROLE_KEY] = role
    coll.objects.link(empty)
    return empty


def clear_markers(scene, role):
    for obj in objects_with_role(scene, role):
        remove_object(obj)


# ---------------------------------------------------------------------------
# Mold box layout
# ---------------------------------------------------------------------------

def mold_bounds(settings, scene):
    """Mold block bounds (lo, hi) from the cached master bounds plus padding."""
    pad = mm(scene, settings.padding)
    lo = Vector(settings.master_min) - Vector((pad, pad, pad))
    hi = Vector(settings.master_max) + Vector((pad, pad, pad))
    return lo, hi


def parting_coordinate(settings, scene):
    axis = AXIS_INDEX[settings.parting_axis]
    center = (settings.master_min[axis] + settings.master_max[axis]) / 2.0
    return center + mm(scene, settings.parting_offset)


def has_layout(settings):
    return any(settings.master_max[i] > settings.master_min[i] for i in range(3))


def sync_parting_preview(scene):
    """Create or move the wireframe rectangle that shows the parting plane."""
    settings = scene.moldsmith
    existing = objects_with_role(scene, ROLE_PARTING)
    if settings.mold_type != "BLOCK" or not settings.show_parting_preview or not has_layout(settings):
        for obj in existing:
            remove_object(obj)
        return

    axis = AXIS_INDEX[settings.parting_axis]
    lo, hi = mold_bounds(settings, scene)
    c = parting_coordinate(settings, scene)
    u, v = [i for i in range(3) if i != axis]
    corners = []
    for a, b in ((lo[u], lo[v]), (hi[u], lo[v]), (hi[u], hi[v]), (lo[u], hi[v])):
        p = [0.0, 0.0, 0.0]
        p[axis], p[u], p[v] = c, a, b
        corners.append(p)

    if existing:
        obj = existing[0]
        for extra in existing[1:]:
            remove_object(extra)
        me = obj.data
        me.clear_geometry()
    else:
        me = bpy.data.meshes.new("MS_Parting")
        obj = bpy.data.objects.new("MS_Parting", me)
        obj[ROLE_KEY] = ROLE_PARTING
        obj.display_type = "WIRE"
        obj.show_in_front = True
        obj.hide_select = True
        ensure_collection(scene, HELPER_COLLECTION).objects.link(obj)
    me.from_pydata(corners, [], [(0, 1, 2, 3)])
    me.update()


def apply_explode(scene):
    """Offset each part along its own explode direction (viewport only)."""
    gap = mm(scene, scene.moldsmith.explode)
    for obj in objects_with_role(scene, ROLE_PART):
        obj.location = Vector(obj.get(EXPLODE_KEY, (0.0, 0.0, 0.0))) * gap
