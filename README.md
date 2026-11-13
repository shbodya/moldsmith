# Moldsmith

A Blender extension (tested on 5.2.1) that turns a model into printable mold
parts. It has two mold types:

- **Block**: a two-part block mold with registration keys, a pour funnel and
  air vents, plus an optional casting kit for pouring silicone (Blender 4.5+).
- **Vessel**: a one-piece silicone mold for open-top vessels such as cups,
  candle jars and planters. It builds a base, a split shell with slide-on
  clamps, and an inner core hung from a bridge (Blender 5.0+, because it uses
  volume grid nodes).

It runs entirely offline with Blender's built-in Manifold boolean solver, so
there are no wheels and it works on any platform.

## Install

```sh
blender --command extension build --source-dir moldsmith --output-dir dist
```

In Blender, open **Edit > Preferences > Get Extensions > ⌄ > Install from Disk…**
and pick `dist/moldsmith-0.3.0.zip`. The panel is in the 3D viewport sidebar
(`N`), on the **Mold** tab.

## Block mold

1. **Select your model and press _Set Up Mold_.** This sizes the mold wall, keys
   and channels to the model and places markers:
   - a sphere empty, **MS_Pour**, at the highest point (on a vertical split it is
     the highest point near the parting plane, so both halves get half the sprue);
   - arrow empties, **MS_Vent**, at the air traps (up-facing local peaks).
   You can move markers with `G`, delete them, or add more at the 3D cursor.
2. **Block & Parting:** choose the split axis and offset. The wireframe rectangle
   shows the parting plane.
3. **Generate Mold.** This creates the collection *Moldsmith Parts*:

   | Part | What it is |
   |---|---|
   | `Mold_A` | Half on the +axis side of the plane, with key sockets (enlarged by *Clearance*). |
   | `Mold_B` | Half on the −axis side, with key knobs. |
   | `Casting_Box_1/2` | Box with an open +axis side, split in two so you can demold (*Casting Kit*). |
   | `Pour_Rods` | Printable sprue and vent rods, trimmed to the master's surface (*Casting Kit*). |

4. **Export STL** writes one binary STL per part, in millimetres.

### Two ways to use the parts

- **Printed rigid mold** (resin, plaster, wax): print `Mold_A` and `Mold_B`,
  close them and pour through the funnel.
- **Silicone mold**: print `Mold_B`, the casting box and the pour rods.
  `Mold_B` is the parting bed.
  1. Put the bed in the box, set the real master into the cavity, and stand the
     rods on the master.
  2. Pour silicone up to the rim. It cures into silicone half A, keys included.
  3. Flip it, remove the bed, apply mold release, and pour silicone half B.

  For a horizontal (Z) split the box opens upward. For X or Y, turn it so the
  open side faces up.

## Vessel mold

For a cup, jar or planter, stand the master upright with its opening facing +Z
and its foot flat. Pick **Vessel** at the top of the panel, select the master
and press **Set Up Mold**. That sizes everything to the model. Then press
**Generate Mold**.

| Part | What it is |
|---|---|
| `Base` | Plate the master stands on, with a lip ring that locates the shell. |
| `Shell_1/2` | Shell halves at *Outer Silicone* distance from the master. Each has a flange with a T-bead along both seams, half of a pin bore in each seam, and a saddle bracket with a V-pocket outside its rim. |
| `Rail_1/2` | T-slot clamps that slide down over a flange pair and hook behind the beads, so they hold the halves shut. |
| `Pin_1/2` | Alignment pins for the blind seam bores. They keep the halves flush, so the silicone has no step at the seam. The easiest pin is a piece of 1.75 mm filament cut to length. The printed pins are a fallback; print them lying down. |
| `Core` | The vessel's interior shrunk by *Inner Silicone*, on a bridge bar that rests on the rim. V-teeth at the bar's ends drop into the saddle pockets and centre the core. |

Print the core upside down, bar on the bed: the column points up and the
V-teeth become ridges, so it needs no supports. Print the shell halves and
clamps upright.

How the parts connect:

- **Shell to base:** the lip ring on the base.
- **Shell half to shell half:** a pin in each seam bore, then a T-slot clamp slid down each seam.
- **Core to shell:** the bridge's V-teeth sit in the saddle pockets. The core can only lift straight up.

How to cast:

1. Put the master on the base and close the shell around it.
2. Drop the pins into the seam bores, then slide the clamps down over the
   flanges.
3. Hang the core so its teeth sit in the saddles.
4. Pour silicone into the gap to *Over Rim* above the vessel's rim. The shell
   rim is 2 mm higher, so it won't overflow.
5. Once it has cured, demold and turn the silicone over. The opening left by the
   master's foot is the fill side: cast your vessel upside down.

The shell follows the master's **convex outline**, not its relief, so a raised
logo or ribs never lock the silicone into the shell. Relief still transfers into
the silicone, because the silicone touches the master.

*Master Recess* sinks the master into the base so it stays put. The cast comes
out shorter by that amount, which is why it defaults to 0. Without a recess, fix
the master to the base with double-sided tape.

## Units

Every setting is in millimetres. If the scene unit scale is 1.0 (Blender's
default), 1 Blender unit is taken as 1 mm, which is what STL files mean. Any
other unit scale (for example 0.001) is used as set.

## Non-watertight models

Flipped faces and mirrored (negative-scale) objects are fixed automatically on
the cavity copy.

The Manifold solver needs a closed mesh. If the master has holes, **Repair
Master** voxel-remeshes a copy of it, and only that copy becomes the cavity; the
original object is never changed. Lower **Voxel Size** for finer detail. You can
also turn repair off and use the **Exact** solver, but the parts may then not be
watertight. **Check Master** reports the non-manifold edges.

## Limitations

- Block: one flat parting plane, aligned to an axis. There are no organic or
  stepped parting lines and no undercut analysis.
- Vessel: the core must come straight up out of the vessel. If the vessel is
  wider inside than at its rim, Generate warns that the core will be hard to
  pull out.
- Vessel: the shell is split in two halves. There is no option for more
  segments, no label tab and no pour-volume estimate yet.
- Vents are straight vertical channels. A vent that rises under an overhang
  passes through the model, so check the vent markers on complex shapes.
- Both mold halves are rectangular blocks (no shaped or shell molds).

## Development

```sh
# headless end-to-end test. Block: torus split on Z/Y/X, a torus with flipped
# faces, a mirrored torus, a non-watertight Suzanne. Vessel: a cup with relief,
# split on X and Y, plus rejecting a closed sphere.
blender --background --factory-startup --python tests/smoke_test.py
```

Code layout (`moldsmith/`):

- `builder.py`: the shared build steps and the block mold.
- `vessel.py`: the vessel mold.
- `geometry.py`: primitives, booleans and mesh analysis.
- `helpers.py`: units, collections, markers and the preview.
- `operators.py`, `panels.py`, `properties.py`: the Blender UI.
- `stl.py`: the STL writer.
