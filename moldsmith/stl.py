"""Minimal binary STL writer (numpy), independent of Blender's exporter context."""

import numpy as np

_FACET = np.dtype([("normal", "<f4", (3,)), ("verts", "<f4", (3, 3)), ("attr", "<u2")])


def write_mesh(path, mesh, scale=1.0):
    """Write the mesh's own coordinates (object transform ignored) scaled by `scale`."""
    mesh.calc_loop_triangles()
    n_tris = len(mesh.loop_triangles)
    tris = np.empty(n_tris * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get("vertices", tris)
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) * scale

    tri_co = co[tris.reshape(-1, 3)]
    normals = np.cross(tri_co[:, 1] - tri_co[:, 0], tri_co[:, 2] - tri_co[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 0)

    facets = np.zeros(n_tris, dtype=_FACET)
    facets["normal"] = normals
    facets["verts"] = tri_co
    with open(path, "wb") as fh:
        header = b"Moldsmith binary STL, units: mm"
        fh.write(header.ljust(80, b"\0"))
        fh.write(np.uint32(n_tris).tobytes())
        fh.write(facets.tobytes())
    return n_tris
