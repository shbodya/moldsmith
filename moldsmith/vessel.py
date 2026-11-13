"""One-piece silicone mold for open-top vessels.

The master stands upright on the base, opening up. Silicone is poured from
the top into the gap between the printed shell, the master and the printed
core, and covers the rim. Once cured and turned over, the silicone is a
mold that is cast upside down through the opening the master's foot left.

    Base      plate with a lip ring that locates the shell; the master stands on it.
    Shell_1/2 halves of a shell that follows the master's convex outline at
              Outer Silicone distance. Each has a flange with a T-bead along
              both seams, half of a pin bore in each seam, and a saddle
              bracket with a V-pocket outside its rim.
    Rail_1/2  T-slot clamps that slide down over a flange pair and hook behind
              the beads, so they hold the halves shut.
    Pin_1/2   alignment pins for the seam bores (1.75 mm filament fits too).
    Core      the vessel's interior shrunk by Inner Silicone, on a bridge bar
              that rests on the rim. V-teeth at the bar's ends drop into the
              saddle pockets and centre it. It keeps the inner silicone a
              thin wall instead of a solid plug.

Shell and base are built from offsets of the master's convex hull, so the shell
has no undercuts even when the master has relief (logos, ribs).
"""

import numpy as np
from mathutils import Vector

from . import geometry as geo
from . import helpers
from .builder import BuildError, Workspace, axis_vector, prepare_cavity, refresh_master_bounds


def auto_size(s, scene):
    from .builder import master_size_mm

    d = master_size_mm(s, scene)

    def clamp(x, lo, hi):
        return max(lo, min(hi, x))

    s.vessel_wall = clamp(0.08 * d, 4.0, 15.0)
    s.vessel_inner = clamp(0.07 * d, 4.0, 12.0)
    s.vessel_top = clamp(0.06 * d, 3.0, 10.0)
    s.flange_width = clamp(0.10 * d, 6.0, 15.0)
    s.bridge_width = clamp(0.12 * d, 8.0, 20.0)
    s.bridge_height = clamp(0.07 * d, 5.0, 10.0)
    s.lip_height = clamp(0.06 * d, 3.0, 8.0)
    s.voxel_size = clamp(d / 400.0, 0.1, 0.5)


def _extended_hull_points(hull, lo_z, hi_z, extend):
    """The master's hull swept straight down below its foot and up above its rim.

    Adds the hull's top-down outline at both extension heights, so the offset
    shell has vertical walls where it is clipped at the base and at the pour
    level, even when the rim or foot is chamfered or rounded. A shell that
    followed a tapering rim inward would trap the silicone.
    """
    up = hull.copy()
    down = hull.copy()
    up[:, 2] = hi_z + extend
    down[:, 2] = lo_z - extend
    return np.vstack([hull, up, down])


def _box(name, lo, hi, collection):
    return geo.bmesh_to_object(name, geo.box_bmesh(Vector(lo), Vector(hi)), collection)


def _slab(name, z0, z1, collection, size=1e4):
    return _box(name, (-size, -size, z0), (size, size, z1), collection)


def build(context):
    scene = context.scene
    s = scene.moldsmith
    if s.master is None:
        raise BuildError("Pick a master object first")
    if not geo.sdf_available():
        raise BuildError("Vessel molds need Blender 5.0 or newer (volume grid nodes)")

    warnings = []
    refresh_master_bounds(context, s)
    mm = lambda v: helpers.mm(scene, v)  # noqa: E731

    lo, hi = Vector(s.master_min), Vector(s.master_max)
    center = (lo + hi) / 2.0
    ax = geo.AXIS_INDEX[s.vessel_split]  # shell halves on -ax / +ax
    ay = 1 - ax  # seams, flanges and rails on -ay / +ay

    t_out, t_in, t_top = mm(s.vessel_wall), mm(s.vessel_inner), mm(s.vessel_top)
    wall, gap = mm(s.box_wall), mm(s.box_clearance)
    ft, fw, rw = mm(s.flange_thickness), mm(s.flange_width), mm(s.rail_wall)
    bw, bh = mm(s.bridge_width), mm(s.bridge_height)
    base_t, lip_h, recess = mm(s.base_thickness), mm(s.lip_height), mm(s.recess_depth)
    voxel = mm(s.voxel_size)
    if recess >= base_t:
        raise BuildError("Master Recess must be thinner than the base")

    hook = mm(s.clamp_hook)
    bead = max(mm(2.5), 2.0 * hook)  # depth of the T-bead at the flange tip
    lip = fw - bead - 2.0 * gap  # rail lips sit between the shell wall and the bead
    if lip < mm(1.2):
        raise BuildError("Flange Width is too small for the clamp hooks; make the flanges wider")
    pin_r = mm(s.pin_diameter) / 2.0
    use_pins = s.use_pins
    if use_pins and (fw - bead < 2.0 * pin_r + mm(2.0) or ft < pin_r + mm(1.0)):
        use_pins = False
        warnings.append("Flanges too small for the alignment pins; pins skipped (widen or thicken the flanges)")

    z_foot = lo.z
    z_base = z_foot + recess  # base top surface: silicone starts here
    z_pour = hi.z + t_top  # silicone level
    z_rim = z_pour + mm(2.0)  # shell rim, a little above the silicone; the bridge rests on it
    z_flange = z_base + lip_h + gap  # flanges and rails start above the base lip
    e = mm(1.0)  # cutter overshoot

    def at(a, b, z):
        """World point from split-frame coordinates (a along ax, b along ay)."""
        v = Vector((0.0, 0.0, z))
        v[ax], v[ay] = a, b
        return v

    def fbox(name, a0, a1, b0, b1, z0, z1, collection):
        return _box(name, at(min(a0, a1), min(b0, b1), min(z0, z1)), at(max(a0, a1), max(b0, b1), max(z0, z1)), collection)

    def fhull(name, abz, collection):
        return geo.convex_hull_object(name, np.array([at(*p)[:] for p in abz]), collection)

    ca, cb = center[ax], center[ay]

    with Workspace(context, 8) as ws:
        work = ws.work
        cavity, solver = prepare_cavity(context, s, work, warnings)

        extend = t_out + wall + gap + rw + base_t + bh + lip_h + bw + 10.0 * voxel
        master_hull = geo.hull_points(geo.mesh_coords(cavity))
        hull_pts = _extended_hull_points(master_hull, lo.z, hi.z, extend)

        def offset(name, distance):
            return geo.convex_offset_object(name, hull_pts, distance, work)

        ws.progress(1)

        # --- Shell -----------------------------------------------------------
        shell = offset("_ms_shell", t_out + wall)
        shell_in = offset("_ms_shell_in", t_out)
        s_lo = Vector(np.min(geo.mesh_coords(shell), axis=0))
        s_hi = Vector(np.max(geo.mesh_coords(shell), axis=0))
        seams = ((1, s_hi[ay], "1"), (-1, s_lo[ay], "2"))  # (side, outer wall along ay, suffix)
        ends = ((1, s_hi[ax]), (-1, s_lo[ax]))  # bridge ends, outer wall along ax

        # Saddle geometry: a V-pocket in a bracket outside each half's rim.
        reach = max(bw, mm(8.0)) + wall  # how far a saddle sticks out from the wall
        v_half = bw / 2.0 + gap  # half-width of the pocket at the rim
        saddle_half = v_half + wall
        saddle_drop = v_half + wall  # saddle thickness at its outer end

        additions = ws.sub("_ms_shell_add")
        for sign, edge, _suffix in seams:
            # Flange plus the T-bead the clamp hooks behind.
            fbox(f"_ms_flange_{sign}", ca - ft, ca + ft, cb, edge + sign * fw, z_flange, z_rim, additions)
            fbox(f"_ms_bead_{sign}", ca - ft - hook, ca + ft + hook,
                 edge + sign * (fw - bead), edge + sign * fw, z_flange, z_rim, additions)
        for sign, edge in ends:
            tip = edge + sign * reach
            pts = []
            for b in (cb - saddle_half, cb + saddle_half):
                pts += [(ca, b, z_rim), (tip, b, z_rim), (tip, b, z_rim - saddle_drop)]
                # 45-degree gusset back to the wall, so it prints without supports
                pts += [(ca, b, z_rim - saddle_drop - reach), (edge, b, z_rim - saddle_drop - reach)]
            fhull(f"_ms_saddle_{sign}", pts, additions)
        geo.apply_boolean(context, shell, additions, "UNION", "MANIFOLD")
        geo.apply_boolean(context, shell, shell_in, "DIFFERENCE", "MANIFOLD")
        geo.apply_boolean(context, shell, _slab("_ms_shell_slab", z_base, z_rim, work), "INTERSECT", "MANIFOLD")

        cuts = ws.sub("_ms_shell_cut")
        for sign, edge in ends:
            a0, a1 = edge, edge + sign * (reach - wall)
            pts = []
            for a in (a0, a1):
                pts += [(a, cb - v_half - e, z_rim + e), (a, cb + v_half + e, z_rim + e), (a, cb, z_rim - v_half)]
            fhull(f"_ms_pocket_{sign}", pts, cuts)
        pins = []
        if use_pins:
            for sign, edge, suffix in seams:
                b_pin = edge + sign * (fw - bead) / 2.0
                # Blind bore: the pin rests on its floor instead of dropping through,
                # and stands proud of the rim so it can be pulled out.
                floor = z_flange + wall
                bore = geo.frustum_bmesh(at(ca, b_pin, floor), at(ca, b_pin, z_rim + e), pin_r + gap / 2.0, pin_r + gap / 2.0, 24)
                geo.bmesh_to_object(f"_ms_bore_{suffix}", bore, cuts)
                pin = geo.frustum_bmesh(at(ca, b_pin, floor), at(ca, b_pin, z_rim + mm(4.0)), pin_r, pin_r, 24)
                pins.append((geo.bmesh_to_object(f"Pin_{suffix}", pin, work), at(0.0, sign * 0.5, 1.5) - at(0.0, 0.0, 0.0)))
        geo.apply_boolean(context, shell, cuts, "DIFFERENCE", "MANIFOLD")

        halves = []
        for sign, suffix in ((1, "1"), (-1, "2")):
            h_lo, h_hi = Vector((-1e4, -1e4, -1e4)), Vector((1e4, 1e4, 1e4))
            if sign > 0:
                h_lo[ax] = ca
            else:
                h_hi[ax] = ca
            half = geo.duplicate(shell, f"Shell_{suffix}", work)
            geo.apply_boolean(context, half, _box(f"_ms_half_{suffix}", h_lo, h_hi, work), "INTERSECT", "MANIFOLD")
            halves.append((half, axis_vector(ax, sign)))
        ws.progress(3)

        # --- Clamp rails: T-slots that slide down over flange + bead ---------
        rails = []
        for sign, edge, suffix in seams:
            near, back = edge + sign * gap, edge + sign * (fw + gap + rw)
            rail = fbox(f"Rail_{suffix}", ca - ft - hook - gap - rw, ca + ft + hook + gap + rw,
                        near, back, z_flange, z_rim, work)
            slots = ws.sub(f"_ms_slot_{suffix}")
            fbox(f"_ms_neck_{suffix}", ca - ft - gap, ca + ft + gap,
                 near - sign * e, edge + sign * (fw + gap), z_flange - e, z_rim + e, slots)
            fbox(f"_ms_hook_{suffix}", ca - ft - hook - gap, ca + ft + hook + gap,
                 edge + sign * (fw - bead - gap), edge + sign * (fw + gap), z_flange - e, z_rim + e, slots)
            geo.apply_boolean(context, rail, slots, "DIFFERENCE", "MANIFOLD")
            rails.append((rail, axis_vector(ay, sign)))
        ws.progress(4)

        # --- Base ------------------------------------------------------------
        base = offset("Base", t_out + wall + gap + wall)
        geo.apply_boolean(
            context, base, _slab("_ms_base_slab", z_base - base_t, z_base + lip_h, work), "INTERSECT", "MANIFOLD"
        )
        socket = offset("_ms_lip_in", t_out + wall + gap)
        geo.apply_boolean(context, socket, _slab("_ms_lip_slab", z_base, z_base + lip_h + mm(1.0), work), "INTERSECT", "MANIFOLD")
        geo.apply_boolean(context, base, socket, "DIFFERENCE", "MANIFOLD")
        if recess > 0.0:
            pocket = offset("_ms_recess", gap)
            geo.apply_boolean(context, pocket, _slab("_ms_recess_slab", z_foot, z_base + mm(1.0), work), "INTERSECT", "MANIFOLD")
            geo.apply_boolean(context, base, pocket, "DIFFERENCE", "MANIFOLD")
        ws.progress(5)

        # --- Core ------------------------------------------------------------
        core = geo.convex_hull_object("Core", master_hull, work)
        hull_volume = geo.mesh_volume(core)
        geo.apply_boolean(context, core, cavity, "DIFFERENCE", solver)
        geo.keep_largest_component(core)
        interior = geo.mesh_volume(core) if not geo.is_empty(core) else 0.0
        if interior < 0.05 * hull_volume:
            raise BuildError("The master has no opening at the top; Vessel mode needs an open cup or jar standing upright")

        # The core only sets the inner silicone thickness (the silicone takes the
        # detail from the master), so a coarse grid is enough and much faster.
        core_voxel = max(voxel, min(mm(1.0), t_in / 8.0))
        # The grid surface lands about a quarter voxel outside the true offset.
        geo.apply_sdf_offset(context, core, -(t_in + core_voxel * 0.25), core_voxel)
        if geo.is_empty(core):
            raise BuildError("Inner Silicone is thicker than the vessel's opening allows")
        geo.keep_largest_component(core)

        core_co = geo.mesh_coords(core)
        core_top = core_co[:, 2].max()
        neck = core_co[core_co[:, 2] > core_top - max(core_voxel * 2.0, (core_top - core_co[:, 2].min()) * 0.02)]
        column_pts = np.vstack([neck, neck + np.array([0.0, 0.0, z_rim + bh - neck[:, 2].min()])])
        column = geo.convex_hull_object("_ms_column", column_pts, work)
        neck_lo, neck_hi = neck.min(axis=0), neck.max(axis=0)
        body_lo, body_hi = core_co.min(axis=0), core_co.max(axis=0)
        if (neck_lo[:2] - body_lo[:2]).max() > gap or (body_hi[:2] - neck_hi[:2]).max() > gap:
            warnings.append("The vessel is wider inside than at its rim; the core will be hard to pull out")

        # Bridge bar resting on the rim, with a V-tooth at each end that drops
        # into the saddle pocket and centres the core in both directions.
        bridge_parts = ws.sub("_ms_bridge")
        bridge_parts.objects.link(column)
        work.objects.unlink(column)
        fbox("_ms_bridge_bar", s_lo[ax] - reach, s_hi[ax] + reach, cb - bw / 2, cb + bw / 2, z_rim, z_rim + bh, bridge_parts)
        for sign, edge in ends:
            a0, a1 = edge + sign * gap, edge + sign * (reach - wall - gap)
            pts = []
            for a in (a0, a1):
                pts += [(a, cb - bw / 2, z_rim + e), (a, cb + bw / 2, z_rim + e),
                        (a, cb - bw / 2, z_rim), (a, cb + bw / 2, z_rim), (a, cb, z_rim - bw / 2)]
            fhull(f"_ms_tooth_{sign}", pts, bridge_parts)
        geo.apply_boolean(context, core, bridge_parts, "UNION", "MANIFOLD")
        ws.progress(7)

        parts = halves + rails + pins + [(base, Vector((0.0, 0.0, -1.0))), (core, Vector((0.0, 0.0, 2.0)))]
        published = ws.publish(parts)

    helpers.apply_explode(scene)
    return published, warnings
