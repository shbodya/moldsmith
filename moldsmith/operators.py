import os

import bpy
from bpy.props import BoolProperty

from . import builder, geometry as geo, helpers, stl, vessel


def _settings(context):
    return context.scene.moldsmith


def _has_master(context):
    return _settings(context).master is not None


class MOLDSMITH_OT_setup(bpy.types.Operator):
    """Use the active object as the master, size the mold and place pour/vent markers"""

    bl_idname = "moldsmith.setup"
    bl_label = "Set Up Mold"
    bl_options = {"REGISTER", "UNDO"}

    auto_size: BoolProperty(
        name="Auto Size",
        default=True,
        description="Scale wall, keys and channels to the size of the master",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and helpers.ROLE_KEY not in obj

    def execute(self, context):
        scene = context.scene
        s = _settings(context)
        s.master = context.active_object
        report = geo.manifold_report(s.master, context.evaluated_depsgraph_get())
        try:
            co, nrm, edges = builder.refresh_master_bounds(context, s, report)
        except builder.BuildError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if self.auto_size:
            builder.auto_size(s, scene)
            if s.mold_type == "VESSEL":
                vessel.auto_size(s, scene)
        s.parting_offset = 0.0

        helpers.clear_markers(scene, helpers.ROLE_POUR)
        helpers.clear_markers(scene, helpers.ROLE_VENT)
        msg = f"Mold set up: {builder.master_size_mm(s, scene):.1f} mm master"
        if s.mold_type == "BLOCK":
            point = builder.choose_pour_point(s, scene, co, nrm)
            helpers.add_marker(scene, helpers.ROLE_POUR, point, helpers.mm(scene, s.funnel_radius))
            vents = builder.place_auto_vents(s, scene, co, nrm, edges)
            msg += f", {vents} vent(s)"
        helpers.sync_parting_preview(scene)

        if report["non_manifold_edges"]:
            msg += f"; master has {report['non_manifold_edges']} non-manifold edges (Repair Master will fix the cavity)"
            self.report({"WARNING"}, msg)
        else:
            if report["flipped_edges"]:
                msg += "; flipped faces will be fixed on the cavity copy"
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class MOLDSMITH_OT_auto_vents(bpy.types.Operator):
    """Replace the vent markers with vents at the master's air traps"""

    bl_idname = "moldsmith.auto_vents"
    bl_label = "Find Air Traps"
    bl_options = {"REGISTER", "UNDO"}

    poll = classmethod(lambda cls, context: _has_master(context))

    def execute(self, context):
        s = _settings(context)
        report = geo.manifold_report(s.master, context.evaluated_depsgraph_get())
        co, nrm, edges = builder.refresh_master_bounds(context, s, report)
        n = builder.place_auto_vents(s, context.scene, co, nrm, edges)
        self.report({"INFO"}, f"Placed {n} vent(s)")
        return {"FINISHED"}


class MOLDSMITH_OT_add_marker(bpy.types.Operator):
    """Add a pour or vent marker at the 3D cursor"""

    bl_idname = "moldsmith.add_marker"
    bl_label = "Add Marker"
    bl_options = {"REGISTER", "UNDO"}

    role: bpy.props.EnumProperty(
        items=((helpers.ROLE_VENT, "Vent", ""), (helpers.ROLE_POUR, "Pour", "")),
        default=helpers.ROLE_VENT,
    )

    def execute(self, context):
        scene = context.scene
        s = _settings(context)
        size = helpers.mm(scene, s.funnel_radius if self.role == helpers.ROLE_POUR else s.vent_radius * 4.0)
        marker = helpers.add_marker(scene, self.role, scene.cursor.location.copy(), size)
        for obj in context.selected_objects:
            obj.select_set(False)
        marker.select_set(True)
        context.view_layer.objects.active = marker
        return {"FINISHED"}


class MOLDSMITH_OT_check_master(bpy.types.Operator):
    """Check that the master is watertight"""

    bl_idname = "moldsmith.check_master"
    bl_label = "Check Master"

    poll = classmethod(lambda cls, context: _has_master(context))

    def execute(self, context):
        r = geo.manifold_report(_settings(context).master, context.evaluated_depsgraph_get())
        if r["is_watertight"]:
            self.report({"INFO"}, f"Watertight: {r['faces']} faces")
        elif r["non_manifold_edges"] == 0:
            self.report(
                {"INFO"},
                f"Closed, but {r['flipped_edges']} edges join flipped faces. "
                "Generate fixes this on its own copy of the master",
            )
        else:
            self.report(
                {"WARNING"},
                f"{r['non_manifold_edges']} non-manifold edges ({r['boundary_edges']} open). "
                "Try Mesh > Clean Up, or a Remesh modifier",
            )
        return {"FINISHED"}


class MOLDSMITH_OT_generate(bpy.types.Operator):
    """Build the mold parts for the selected mold type"""

    bl_idname = "moldsmith.generate"
    bl_label = "Generate Mold"
    bl_options = {"REGISTER", "UNDO"}

    poll = classmethod(lambda cls, context: _has_master(context))

    def execute(self, context):
        build = vessel.build if _settings(context).mold_type == "VESSEL" else builder.build
        try:
            parts, warnings = build(context)
        except builder.BuildError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for w in warnings:
            self.report({"WARNING"}, w)
        self.report({"INFO"}, "Generated " + ", ".join(p.name for p in parts))
        return {"FINISHED"}


class MOLDSMITH_OT_export(bpy.types.Operator):
    """Write every generated part as a binary STL in millimetres"""

    bl_idname = "moldsmith.export"
    bl_label = "Export STL"

    @classmethod
    def poll(cls, context):
        return bool(helpers.objects_with_role(context.scene, helpers.ROLE_PART))

    def execute(self, context):
        scene = context.scene
        s = _settings(context)
        if s.export_dir.startswith("//") and not bpy.data.filepath:
            self.report({"ERROR"}, "Save the .blend file first, or choose an absolute export folder")
            return {"CANCELLED"}
        folder = bpy.path.abspath(s.export_dir)
        os.makedirs(folder, exist_ok=True)

        prefix = bpy.path.clean_name(s.master.name) + "_" if s.master else ""
        scale = helpers.mm_per_unit(scene)
        written = []
        for obj in helpers.objects_with_role(scene, helpers.ROLE_PART):
            path = os.path.join(folder, f"{prefix}{bpy.path.clean_name(obj.name)}.stl")
            stl.write_mesh(path, obj.data, scale)
            written.append(os.path.basename(path))
        self.report({"INFO"}, f"Wrote {len(written)} file(s) to {folder}")
        return {"FINISHED"}


class MOLDSMITH_OT_clear(bpy.types.Operator):
    """Remove generated parts and helper markers (the master is untouched)"""

    bl_idname = "moldsmith.clear"
    bl_label = "Clear"
    bl_options = {"REGISTER", "UNDO"}

    keep_markers: BoolProperty(name="Keep Markers", default=False)

    def execute(self, context):
        helpers.remove_collection(helpers.OUTPUT_COLLECTION)
        if not self.keep_markers:
            helpers.remove_collection(helpers.HELPER_COLLECTION)
        return {"FINISHED"}


classes = (
    MOLDSMITH_OT_setup,
    MOLDSMITH_OT_auto_vents,
    MOLDSMITH_OT_add_marker,
    MOLDSMITH_OT_check_master,
    MOLDSMITH_OT_generate,
    MOLDSMITH_OT_export,
    MOLDSMITH_OT_clear,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
