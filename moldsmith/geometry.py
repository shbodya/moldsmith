"""Mesh primitives, mesh analysis and boolean helpers.

Everything here works in world space. Generated objects keep an identity
transform so their mesh coordinates are the coordinates that get exported.
"""

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


# ---------------------------------------------------------------------------
# Mesh analysis
# ---------------------------------------------------------------------------

def evaluated_arrays(obj, depsgraph, fix_winding=False):
    """Return (coords, normals, edges) of an object's evaluated mesh in world space.

    With `fix_winding`, normals come from a copy with consistent face winding,
    so up-facing tests work on meshes with flipped faces.
    """
    eval_obj = obj.evaluated_get(depsgraph)
    if fix_winding:
        me = bpy.data.meshes.new_from_object(eval_obj)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    else:
        me = eval_obj.to_mesh()
    try:
        n_verts = len(me.vertices)
        co = np.empty(n_verts * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        nrm = np.empty(n_verts * 3, dtype=np.float64)
        me.vertex_normals.foreach_get("vector", nrm)
        edges = np.empty(len(me.edges) * 2, dtype=np.int64)
        me.edges.foreach_get("vertices", edges)
    finally:
        if fix_winding:
            bpy.data.meshes.remove(me)
        else:
            eval_obj.to_mesh_clear()

    mat = np.array(obj.matrix_world, dtype=np.float64)
    co = co.reshape(-1, 3) @ mat[:3, :3].T + mat[:3, 3]
    # Normals transform with the inverse transpose.
    nmat = np.array(obj.matrix_world.to_3x3().inverted_safe().transposed(), dtype=np.float64)
    nrm = nrm.reshape(-1, 3) @ nmat.T
    lengths = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, lengths, out=np.zeros_like(nrm), where=lengths > 0)
    return co, nrm, edges.reshape(-1, 2)


def manifold_report(obj, depsgraph):
    """Check that a mesh is a closed, consistently wound surface, as booleans need.

    An edge is bad unless exactly two faces use it, in opposite directions.
    A mesh with flipped faces counts as broken: the Manifold solver would
    silently ignore it.
    """
    eval_obj = obj.evaluated_get(depsgraph)
    me = eval_obj.to_mesh()
    try:
        n_edges = len(me.edges)
        n_loops = len(me.loops)
        loop_edge = np.empty(n_loops, dtype=np.int64)
        loop_vert = np.empty(n_loops, dtype=np.int64)
        me.loops.foreach_get("edge_index", loop_edge)
        me.loops.foreach_get("vertex_index", loop_vert)
        edge_verts = np.empty(n_edges * 2, dtype=np.int64)
        me.edges.foreach_get("vertices", edge_verts)
        n_verts, n_faces = len(me.vertices), len(me.polygons)
    finally:
        eval_obj.to_mesh_clear()

    edge_verts = edge_verts.reshape(-1, 2)
    uses = np.bincount(loop_edge, minlength=n_edges)
    forward = np.bincount(loop_edge, weights=loop_vert == edge_verts[loop_edge, 0], minlength=n_edges)
    non_manifold = int(np.count_nonzero(uses != 2))
    flipped = int(np.count_nonzero((uses == 2) & (forward != 1)))
    return {
        "verts": n_verts,
        "faces": n_faces,
        "non_manifold_edges": non_manifold,
        "boundary_edges": int(np.count_nonzero(uses == 1)),
        "flipped_edges": flipped,
        "is_watertight": non_manifold == 0 and flipped == 0 and n_faces > 0,
    }


def mesh_volume(obj):
    """Absolute enclosed volume of an object's mesh (own coordinates)."""
    me = obj.data
    me.calc_loop_triangles()
    tris = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", tris)
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    t = co.reshape(-1, 3)[tris.reshape(-1, 3)]
    return abs(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum()) / 6.0


def recalc_normals(obj):
    """Make face winding consistent and outward (fixes flipped faces, mirrored transforms)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()


def pour_point(co, nrm):
    """Highest up-facing vertex: where the casting material reaches last."""
    up = nrm[:, 2] > 0.0
    candidates = np.flatnonzero(up) if up.any() else np.arange(len(co))
    return Vector(co[candidates[np.argmax(co[candidates, 2])]])


def air_trap_points(co, nrm, edges, exclude, min_separation, max_count, rings=2):
    """Find up-facing local maxima of the surface, where air gets trapped.

    A vertex counts as a local maximum when no vertex within `rings` edge hops
    is higher. Candidates closer than `min_separation` to each other or to any
    point in `exclude` are dropped, keeping the highest first.
    """
    if max_count <= 0 or len(edges) == 0:
        return []
    z = co[:, 2]
    neighbour_max = z.copy()
    for _ in range(rings):
        grown = neighbour_max.copy()
        np.maximum.at(grown, edges[:, 0], neighbour_max[edges[:, 1]])
        np.maximum.at(grown, edges[:, 1], neighbour_max[edges[:, 0]])
        neighbour_max = grown
    is_peak = (z >= neighbour_max) & (nrm[:, 2] > 0.3)
    candidates = np.flatnonzero(is_peak)
    candidates = candidates[np.argsort(-z[candidates])]

    chosen = [np.asarray(p, dtype=np.float64) for p in exclude]
    picked = []
    for idx in candidates:
        p = co[idx]
        if all(np.linalg.norm(p - q) >= min_separation for q in chosen):
            chosen.append(p)
            picked.append(Vector(p))
            if len(picked) >= max_count:
                break
    return picked


# ---------------------------------------------------------------------------
# Primitives (all return a new bmesh in world coordinates)
# ---------------------------------------------------------------------------

def box_bmesh(lo, hi):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    size = Vector(hi) - Vector(lo)
    center = (Vector(hi) + Vector(lo)) / 2.0
    matrix = Matrix.Translation(center) @ Matrix.Diagonal(size.to_4d())
    bmesh.ops.transform(bm, matrix=matrix, verts=bm.verts)
    return bm


def frustum_bmesh(p0, p1, r0, r1, segments=32):
    """Closed truncated cone from p0 (radius r0) to p1 (radius r1). Both radii must be > 0."""
    p0, p1 = Vector(p0), Vector(p1)
    axis = p1 - p0
    length = axis.length
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segments,
        radius1=r0, radius2=r1, depth=length,
    )
    rotation = Vector((0.0, 0.0, 1.0)).rotation_difference(axis.normalized()).to_matrix().to_4x4()
    matrix = Matrix.Translation((p0 + p1) / 2.0) @ rotation
    bmesh.ops.transform(bm, matrix=matrix, verts=bm.verts)
    return bm


def sphere_bmesh(center, radius, subdivisions=3):
    bm = bmesh.new()
    # A small tilt keeps vertices off the parting plane, which avoids coplanar faces.
    tilt = Matrix.Rotation(0.13, 4, "X") @ Matrix.Rotation(0.07, 4, "Y")
    bmesh.ops.create_icosphere(
        bm, subdivisions=subdivisions, radius=radius,
        matrix=Matrix.Translation(Vector(center)) @ tilt,
    )
    return bm


def bmesh_to_object(name, bm, collection):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    return obj


def copy_world_mesh(src, name, collection, depsgraph):
    """Copy an object's evaluated mesh with its transform baked in."""
    me = bpy.data.meshes.new_from_object(src.evaluated_get(depsgraph))
    me.name = name
    me.transform(src.matrix_world)
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    return obj


def duplicate(obj, name, collection):
    copy = bpy.data.objects.new(name, obj.data.copy())
    collection.objects.link(copy)
    return copy


# ---------------------------------------------------------------------------
# Booleans
# ---------------------------------------------------------------------------

def apply_boolean(context, obj, operand, operation, solver):
    """Apply a boolean in place. `operand` is an Object or a Collection."""
    mod = obj.modifiers.new("moldsmith_boolean", "BOOLEAN")
    mod.operation = operation
    mod.solver = solver
    if isinstance(operand, bpy.types.Collection):
        mod.operand_type = "COLLECTION"
        mod.collection = operand
    else:
        mod.operand_type = "OBJECT"
        mod.object = operand
    if solver == "EXACT":
        mod.use_hole_tolerant = True

    depsgraph = context.evaluated_depsgraph_get()
    result = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    obj.modifiers.remove(mod)
    old = obj.data
    result.name = old.name
    obj.data = result
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


def apply_voxel_remesh(context, obj, voxel_size):
    """Rebuild a mesh as a watertight voxel surface (fills holes, fixes self-intersections)."""
    mod = obj.modifiers.new("moldsmith_remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel_size
    mod.adaptivity = 0.0
    depsgraph = context.evaluated_depsgraph_get()
    result = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    obj.modifiers.remove(mod)
    old = obj.data
    result.name = old.name
    obj.data = result
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


def is_empty(obj):
    return len(obj.data.polygons) == 0


# ---------------------------------------------------------------------------
# Convex hulls and offsets
# ---------------------------------------------------------------------------

def _unit_sphere_points(subdivisions=2, ring=48):
    """Icosphere directions plus a horizontal ring.

    The icosphere has no vertices on its equator, which would leave vertical
    offset walls a little short; the ring makes them exact.
    """
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=1.0)
    pts = np.array([v.co[:] for v in bm.verts], dtype=np.float64)
    bm.free()
    angles = np.linspace(0.0, 2.0 * np.pi, ring, endpoint=False)
    equator = np.column_stack([np.cos(angles), np.sin(angles), np.zeros(ring)])
    return np.vstack([pts, equator])


def mesh_coords(obj):
    co = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def hull_points(points):
    """Vertices of the convex hull of a point cloud."""
    obj = convex_hull_object("_ms_hull_tmp", points, None)
    pts = mesh_coords(obj)
    me = obj.data
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(me)
    return pts


def convex_hull_object(name, points, collection):
    """Closed convex hull mesh of a point cloud (interior points dropped)."""
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(points))
    me.vertices.foreach_set("co", np.ascontiguousarray(points, dtype=np.float32).ravel())
    bm = bmesh.new()
    bm.from_mesh(me)
    result = bmesh.ops.convex_hull(bm, input=bm.verts[:], use_existing_faces=False)
    loose = list({v for v in result["geom_interior"] + result["geom_unused"] if isinstance(v, bmesh.types.BMVert)})
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    if collection is not None:
        collection.objects.link(obj)
    return obj


def convex_offset_object(name, points, distance, collection, subdivisions=2):
    """Convex hull of `points` grown by `distance` (Minkowski sum with a sphere).

    Exact on flat faces; edges and corners are rounded by an icosphere, so the
    error is under 1% of `distance`.
    """
    base = hull_points(points)
    if distance > 0.0:
        sphere = _unit_sphere_points(subdivisions) * distance
        base = (base[:, None, :] + sphere[None, :, :]).reshape(-1, 3)
    return convex_hull_object(name, base, collection)


# ---------------------------------------------------------------------------
# Signed-distance offsets (geometry nodes volume grids, Blender 5.x)
# ---------------------------------------------------------------------------

def sdf_available():
    return all(
        hasattr(bpy.types, n)
        for n in ("GeometryNodeMeshToSDFGrid", "GeometryNodeSDFGridOffset", "GeometryNodeGridToMesh")
    )


def apply_sdf_offset(context, obj, distance, voxel_size):
    """Grow (distance > 0) or shrink (distance < 0) a closed mesh in place.

    The node group exists only for the duration of the call.
    """
    group = bpy.data.node_groups.new("_ms_sdf_offset", "GeometryNodeTree")
    try:
        group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        nodes, links = group.nodes, group.links
        g_in = nodes.new("NodeGroupInput")
        g_out = nodes.new("NodeGroupOutput")
        to_sdf = nodes.new("GeometryNodeMeshToSDFGrid")
        offset = nodes.new("GeometryNodeSDFGridOffset")
        to_mesh = nodes.new("GeometryNodeGridToMesh")
        to_sdf.inputs["Voxel Size"].default_value = voxel_size
        # The narrow band must reach the offset surface.
        to_sdf.inputs["Band Width"].default_value = int(abs(distance) / voxel_size) + 4
        offset.inputs["Distance"].default_value = distance
        links.new(g_in.outputs[0], to_sdf.inputs["Mesh"])
        links.new(to_sdf.outputs[0], offset.inputs[0])
        links.new(offset.outputs[0], to_mesh.inputs[0])
        links.new(to_mesh.outputs[0], g_out.inputs[0])

        mod = obj.modifiers.new("moldsmith_sdf", "NODES")
        mod.node_group = group
        depsgraph = context.evaluated_depsgraph_get()
        result = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
        obj.modifiers.remove(mod)
    finally:
        bpy.data.node_groups.remove(group)
    old = obj.data
    result.name = old.name
    obj.data = result
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


# ---------------------------------------------------------------------------
# Connected components
# ---------------------------------------------------------------------------

def keep_largest_component(obj):
    """Delete every loose part of the mesh except the one with the largest volume."""
    me = obj.data
    n = len(me.vertices)
    edges = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)

    # Label propagation over a CSR adjacency, breadth first from each unvisited vertex.
    order = np.argsort(np.concatenate([edges[:, 0], edges[:, 1]]), kind="stable")
    nbrs = np.concatenate([edges[:, 1], edges[:, 0]])[order]
    starts = np.searchsorted(np.concatenate([edges[:, 0], edges[:, 1]])[order], np.arange(n + 1))
    label = np.full(n, -1, dtype=np.int64)
    count = 0
    for seed in range(n):
        if label[seed] != -1:
            continue
        frontier = np.array([seed])
        label[seed] = count
        while frontier.size:
            nxt = np.concatenate([nbrs[starts[v]:starts[v + 1]] for v in frontier])
            nxt = np.unique(nxt[label[nxt] == -1])
            label[nxt] = count
            frontier = nxt
        count += 1
    if count <= 1:
        return 1

    me.calc_loop_triangles()
    tris = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape(-1, 3)
    co = mesh_coords(obj)
    t = co[tris]
    signed = np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])) / 6.0
    volumes = np.bincount(label[tris[:, 0]], weights=signed, minlength=count)
    keep = int(np.argmax(np.abs(volumes)))

    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    doomed = [bm.verts[i] for i in np.flatnonzero(label != keep)]
    bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    return count
