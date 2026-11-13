import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from . import helpers


def _sync_preview(self, context):
    helpers.sync_parting_preview(context.scene)


def _sync_explode(self, context):
    helpers.apply_explode(context.scene)


def _poll_mesh(self, obj):
    return obj.type == "MESH" and helpers.ROLE_KEY not in obj


class MOLDSMITH_PG_settings(bpy.types.PropertyGroup):
    mold_type: EnumProperty(
        name="Mold Type",
        items=(
            ("BLOCK", "Block", "Two-part block mold for any shape"),
            ("VESSEL", "Vessel", "One-piece silicone mold for open-top vessels (cups, planters, candle jars)"),
        ),
        default="BLOCK",
        update=_sync_preview,
    )
    master: PointerProperty(
        name="Master",
        type=bpy.types.Object,
        poll=_poll_mesh,
        description="The model to cast. It is never modified",
    )
    # World-space bounds of the master, cached at setup so the preview stays cheap.
    master_min: FloatVectorProperty(size=3, options={"HIDDEN"})
    master_max: FloatVectorProperty(size=3, options={"HIDDEN"})

    # Block
    padding: FloatProperty(
        name="Mold Wall",
        description="Silicone thickness between the master and the outside of the mold (mm)",
        default=12.0, min=1.0, soft_max=100.0, precision=1,
        update=_sync_preview,
    )

    # Parting
    parting_axis: EnumProperty(
        name="Split Axis",
        description="Axis the parting plane is perpendicular to",
        items=(
            ("X", "X", "Split into left and right halves"),
            ("Y", "Y", "Split into front and back halves"),
            ("Z", "Z", "Split into top and bottom halves"),
        ),
        default="Y",
        update=_sync_preview,
    )
    parting_offset: FloatProperty(
        name="Offset",
        description="Parting plane offset from the master's centre along the split axis (mm)",
        default=0.0, precision=2,
        update=_sync_preview,
    )
    show_parting_preview: BoolProperty(
        name="Show Plane", default=True, update=_sync_preview,
    )

    # Registration keys
    key_shape: EnumProperty(
        name="Key Shape",
        items=(
            ("SPHERE", "Sphere", "Round knobs, easiest to demold"),
            ("CONE", "Cone", "Tapered pins, tighter alignment"),
        ),
        default="SPHERE",
    )
    key_count: EnumProperty(
        name="Keys",
        items=(("2", "2", "Two diagonal keys"), ("4", "4", "One key per corner")),
        default="4",
    )
    key_radius: FloatProperty(
        name="Key Radius", default=4.0, min=0.5, soft_max=30.0, precision=2,
        description="Radius of the registration keys (mm)",
    )
    key_clearance: FloatProperty(
        name="Clearance", default=0.2, min=0.0, soft_max=1.0, precision=2,
        description="Extra room in the sockets so printed halves fit together (mm)",
    )

    # Pour channel and vents
    sprue_radius: FloatProperty(
        name="Sprue Radius", default=3.0, min=0.3, soft_max=20.0, precision=2,
        description="Radius of the pour channel (mm)",
    )
    funnel_radius: FloatProperty(
        name="Funnel Radius", default=8.0, min=0.5, soft_max=50.0, precision=2,
        description="Radius of the funnel opening at the top of the mold (mm)",
    )
    funnel_depth: FloatProperty(
        name="Funnel Depth", default=8.0, min=0.0, soft_max=50.0, precision=2,
        description="Height of the funnel cone (mm)",
    )
    channel_embed: FloatProperty(
        name="Embed", default=1.0, min=0.0, soft_max=10.0, precision=2,
        description="How far channels reach into the master so they connect cleanly (mm)",
    )
    vent_radius: FloatProperty(
        name="Vent Radius", default=1.0, min=0.2, soft_max=5.0, precision=2,
        description="Radius of the air vents (mm)",
    )
    vent_count: IntProperty(
        name="Auto Vents", default=3, min=0, max=32,
        description="How many air traps to vent automatically",
    )

    # Silicone casting kit
    make_casting_kit: BoolProperty(
        name="Casting Kit",
        default=True,
        description="Also build a printable box and pour rods for pouring silicone",
    )
    box_wall: FloatProperty(
        name="Box Wall", default=2.4, min=0.4, soft_max=10.0, precision=2,
        description="Wall thickness of the printed casting box (mm)",
    )
    box_clearance: FloatProperty(
        name="Box Clearance", default=0.3, min=0.0, soft_max=2.0, precision=2,
        description="Gap between the parting bed and the box walls (mm)",
    )
    split_box: BoolProperty(
        name="Split Box", default=True,
        description="Split the casting box in two so the cured silicone comes out easily",
    )

    # Vessel mold
    vessel_wall: FloatProperty(
        name="Outer Silicone", default=8.0, min=1.0, soft_max=40.0, precision=1,
        description="Silicone thickness around the outside of the vessel (mm)",
    )
    vessel_inner: FloatProperty(
        name="Inner Silicone", default=6.0, min=1.0, soft_max=40.0, precision=1,
        description="Silicone thickness between the inside of the vessel and the printed core (mm)",
    )
    vessel_top: FloatProperty(
        name="Over Rim", default=6.0, min=1.0, soft_max=40.0, precision=1,
        description="Silicone thickness above the vessel's rim; this is the pour level (mm)",
    )
    vessel_split: EnumProperty(
        name="Split",
        items=(
            ("X", "X", "Shell halves on -X and +X, clamps on the Y sides"),
            ("Y", "Y", "Shell halves on -Y and +Y, clamps on the X sides"),
        ),
        default="X",
    )
    flange_thickness: FloatProperty(
        name="Flange", default=3.0, min=1.0, soft_max=10.0, precision=1,
        description="Thickness of each half's clamping flange (mm)",
    )
    flange_width: FloatProperty(
        name="Flange Width", default=8.0, min=3.0, soft_max=30.0, precision=1,
        description="How far the flanges stick out from the shell (mm)",
    )
    rail_wall: FloatProperty(
        name="Clamp Wall", default=2.4, min=0.8, soft_max=8.0, precision=1,
        description="Wall thickness of the slide-on clamp rails (mm)",
    )
    clamp_hook: FloatProperty(
        name="Clamp Hook", default=1.5, min=0.5, soft_max=5.0, precision=1,
        description="How far the flange bead sticks out sideways for the clamp to hook behind (mm)",
    )
    use_pins: BoolProperty(
        name="Seam Pins", default=True,
        description="Bore a pin hole down each seam and generate pins that keep the halves aligned",
    )
    pin_diameter: FloatProperty(
        name="Pin Diameter", default=1.75, min=1.0, soft_max=6.0, precision=2,
        description="Diameter of the seam pins; 1.75 mm lets you use a piece of filament (mm)",
    )
    bridge_width: FloatProperty(
        name="Bridge Width", default=10.0, min=3.0, soft_max=40.0, precision=1,
        description="Width of the bar that hangs the core from the shell rim (mm)",
    )
    bridge_height: FloatProperty(
        name="Bridge Height", default=6.0, min=2.0, soft_max=20.0, precision=1,
        description="Height of the core's bridge bar (mm)",
    )
    base_thickness: FloatProperty(
        name="Base", default=3.0, min=1.0, soft_max=10.0, precision=1,
        description="Thickness of the base plate (mm)",
    )
    lip_height: FloatProperty(
        name="Lip Height", default=5.0, min=1.0, soft_max=20.0, precision=1,
        description="Height of the ring on the base that locates the shell (mm)",
    )
    recess_depth: FloatProperty(
        name="Master Recess", default=0.0, min=0.0, soft_max=3.0, precision=2,
        description="Sink the master into the base to locate it. The cast comes out this much shorter (mm)",
    )

    # Output
    solver: EnumProperty(
        name="Solver",
        items=(
            ("AUTO", "Auto", "Manifold when the master is watertight, Exact otherwise"),
            ("MANIFOLD", "Manifold", "Fast and robust, needs a watertight master"),
            ("EXACT", "Exact", "Slower, tolerates small holes in the master"),
        ),
        default="AUTO",
    )
    voxel_repair: BoolProperty(
        name="Repair Master",
        default=True,
        description="If the master is not watertight, voxel-remesh a copy of it for the cavity",
    )
    voxel_size: FloatProperty(
        name="Voxel Size", default=0.25, min=0.02, soft_max=2.0, precision=3,
        description="Detail of the repaired cavity. Smaller is finer and slower (mm)",
    )
    explode: FloatProperty(
        name="Explode", default=0.0, min=0.0, soft_max=100.0, precision=1,
        description="Pull the mold halves apart in the viewport (mm). Export is not affected",
        update=_sync_explode,
    )
    export_dir: StringProperty(
        name="Folder", subtype="DIR_PATH", default="//mold_parts/",
        description="Where STL files are written",
    )


classes = (MOLDSMITH_PG_settings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.moldsmith = PointerProperty(type=MOLDSMITH_PG_settings)


def unregister():
    del bpy.types.Scene.moldsmith
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
