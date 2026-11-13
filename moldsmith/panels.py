import bpy

from . import helpers


class _MoldsmithPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mold"


class _BlockPanel(_MoldsmithPanel):
    @classmethod
    def poll(cls, context):
        return context.scene.moldsmith.mold_type == "BLOCK"


class _VesselPanel(_MoldsmithPanel):
    @classmethod
    def poll(cls, context):
        return context.scene.moldsmith.mold_type == "VESSEL"


class MOLDSMITH_PT_main(_MoldsmithPanel, bpy.types.Panel):
    bl_idname = "MOLDSMITH_PT_main"
    bl_label = "Moldsmith"

    def draw(self, context):
        layout = self.layout
        s = context.scene.moldsmith
        layout.prop(s, "mold_type", expand=True)
        layout.prop(s, "master")
        row = layout.row(align=True)
        row.operator("moldsmith.setup", icon="MOD_BUILD")
        row.operator("moldsmith.check_master", text="", icon="CHECKMARK")
        if s.master is None:
            layout.label(text="Select your model and press Set Up Mold", icon="INFO")


class MOLDSMITH_PT_block(_BlockPanel, bpy.types.Panel):
    bl_label = "Block & Parting"
    bl_parent_id = "MOLDSMITH_PT_main"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        s = context.scene.moldsmith
        layout.prop(s, "padding")
        layout.prop(s, "parting_axis", expand=True)
        layout.prop(s, "parting_offset")
        layout.prop(s, "show_parting_preview")


class MOLDSMITH_PT_keys(_BlockPanel, bpy.types.Panel):
    bl_label = "Registration Keys"
    bl_parent_id = "MOLDSMITH_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        s = context.scene.moldsmith
        layout.prop(s, "key_shape", expand=True)
        layout.prop(s, "key_count", expand=True)
        layout.prop(s, "key_radius")
        layout.prop(s, "key_clearance")


class MOLDSMITH_PT_channels(_BlockPanel, bpy.types.Panel):
    bl_label = "Pour & Vents"
    bl_parent_id = "MOLDSMITH_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        scene = context.scene
        s = scene.moldsmith
        col = layout.column(align=True)
        col.prop(s, "sprue_radius")
        col.prop(s, "funnel_radius")
        col.prop(s, "funnel_depth")
        col.prop(s, "channel_embed")
        col = layout.column(align=True)
        col.prop(s, "vent_radius")
        col.prop(s, "vent_count")

        pours = len(helpers.objects_with_role(scene, helpers.ROLE_POUR))
        vents = len(helpers.objects_with_role(scene, helpers.ROLE_VENT))
        layout.use_property_split = False
        layout.label(text=f"{pours} pour, {vents} vent marker(s). Move them with G", icon="EMPTY_AXIS")
        row = layout.row(align=True)
        row.operator("moldsmith.auto_vents", icon="FORCE_WIND")
        row.operator("moldsmith.add_marker", text="Vent at Cursor", icon="CURSOR").role = helpers.ROLE_VENT
        layout.operator("moldsmith.add_marker", text="Pour at Cursor", icon="CURSOR").role = helpers.ROLE_POUR


class MOLDSMITH_PT_kit(_BlockPanel, bpy.types.Panel):
    bl_label = "Silicone Casting Kit"
    bl_parent_id = "MOLDSMITH_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.prop(context.scene.moldsmith, "make_casting_kit", text="")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        s = context.scene.moldsmith
        layout.active = s.make_casting_kit
        layout.prop(s, "box_wall")
        layout.prop(s, "box_clearance")
        layout.prop(s, "split_box")


class MOLDSMITH_PT_vessel(_VesselPanel, bpy.types.Panel):
    bl_label = "Silicone & Shell"
    bl_parent_id = "MOLDSMITH_PT_main"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        s = context.scene.moldsmith
        col = layout.column(align=True)
        col.prop(s, "vessel_wall")
        col.prop(s, "vessel_inner")
        col.prop(s, "vessel_top")
        col = layout.column(align=True)
        col.prop(s, "box_wall", text="Shell Wall")
        col.prop(s, "box_clearance", text="Clearance")
        layout.prop(s, "vessel_split", expand=True)


class MOLDSMITH_PT_vessel_parts(_VesselPanel, bpy.types.Panel):
    bl_label = "Clamps, Core & Base"
    bl_parent_id = "MOLDSMITH_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        s = context.scene.moldsmith
        col = layout.column(align=True)
        col.prop(s, "flange_thickness")
        col.prop(s, "flange_width")
        col.prop(s, "rail_wall")
        col.prop(s, "clamp_hook")
        col = layout.column(align=True)
        col.prop(s, "use_pins")
        sub = col.column(align=True)
        sub.active = s.use_pins
        sub.prop(s, "pin_diameter")
        col = layout.column(align=True)
        col.prop(s, "bridge_width")
        col.prop(s, "bridge_height")
        col = layout.column(align=True)
        col.prop(s, "base_thickness")
        col.prop(s, "lip_height")
        col.prop(s, "recess_depth")


class MOLDSMITH_PT_output(_MoldsmithPanel, bpy.types.Panel):
    bl_label = "Generate & Export"
    bl_parent_id = "MOLDSMITH_PT_main"

    def draw(self, context):
        layout = self.layout
        s = context.scene.moldsmith
        col = layout.column()
        col.use_property_split = True
        col.prop(s, "solver")
        col.prop(s, "voxel_repair")
        sub = col.column()
        sub.active = s.voxel_repair
        sub.prop(s, "voxel_size")
        layout.operator("moldsmith.generate", icon="MESH_CUBE")
        col = layout.column()
        col.use_property_split = True
        col.prop(s, "explode")
        col.prop(s, "export_dir")
        row = layout.row(align=True)
        row.operator("moldsmith.export", icon="EXPORT")
        row.operator("moldsmith.clear", text="", icon="TRASH")


classes = (
    MOLDSMITH_PT_main,
    MOLDSMITH_PT_block,
    MOLDSMITH_PT_keys,
    MOLDSMITH_PT_channels,
    MOLDSMITH_PT_kit,
    MOLDSMITH_PT_vessel,
    MOLDSMITH_PT_vessel_parts,
    MOLDSMITH_PT_output,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
