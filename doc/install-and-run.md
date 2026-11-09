# Install and run

## Install

Install as a package (adds the `b2gm` console commands) — from a clone:

```powershell
pip install .            # or: pip install -e .   (editable / development)
```

or straight from GitHub:

```powershell
pip install "git+https://github.com/mac999/ISO19166-B2GM.git"
```

Optional extras: `pip install ".[geo]"` (GeoJSON via geopandas), `".[viz]"`
(pyvista/pydeck 3D viewers), `".[citygml]"` (typed CityGML via xsdata), or
`".[all]"`. Core dependencies (ifcopenshell, pyproj, shapely, numpy, tqdm) are
installed automatically.

Installing exposes four console commands:

| Command | Equivalent module | Purpose |
|---------|-------------------|---------|
| `b2gm` | `B2GM_main` | run the full PD → CM → EM → LM pipeline |
| `b2gm-extrude` | `B2GM_LM_op_extrude` | footprint → LOD1 solid extrusion |
| `b2gm-em` | `B2GM_element` | element-mapping stage (stand-alone) |
| `b2gm-lm` | `B2GM_LM` | LoD-mapping stage (stand-alone) |
| `b2gm-web` | `B2GM_web` | web view (3D canvas + pipeline panels) |

```powershell
b2gm --help
b2gm --input my_building.ifc --pipeline my_pipeline.json --output-dir out
```

The bundled example (`input_data/`) resolves automatically for a repo clone or an
editable install, so a bare `b2gm` runs it; a non-editable install has no bundled
data, so pass `--input`/`--pipeline` explicitly. To build distributables:
`pip install build && python -m build` (produces `dist/*.whl` and `*.tar.gz`).

Or just install the runtime dependencies without packaging:

```powershell
pip install -r requirements.txt
```

## Run

### A folder of buildings

`--input` also takes a folder. Each sub-folder is one building and holds the
pipeline JSON that maps it, so PD, EM, LM and CM can differ from building to
building; the IFC is a file in that folder or the one named by the pipeline's
top-level `input` key, relative to the folder, so a sample model can be placed
many times without copies:

```
input_data/teheran-ro/
  box_ifc4.ifc
  01_duplex_block/pipeline.json        "input": "../../duplex_apartment.ifc"
  02_duplex_envelope/pipeline.json
  03_box_openings/pipeline.json        "input": "../box_ifc4.ifc"
  ...
```

```bash
python B2GM_main.py --input input_data/teheran-ro --output-dir output/teheran-ro
```

Every building is written under `output/teheran-ro/<building>/` and the final
CityGML files are merged into `output/teheran-ro/teheran-ro.gml`: one
`CityModel`, one `cityObjectMember` per building, the envelope recomputed and
every `gml:id` prefixed with the building folder so a model placed twice does
not collide. All buildings must come out in the same CityGML version
(`--citygml-version` applies to all of them); a mixed set is reported and not
merged. A folder without a pipeline JSON, or whose IFC cannot be found, is
skipped with a log line.

The shipped `teheran-ro` district places twenty buildings along Teheran-ro
between Seolleung and Samseong stations in Seoul, in EPSG:5186, with the CM
stage last so the LoD operators work in metres. The positions are illustrative,
not surveyed. Four profiles rotate through the folders:

| Profile | PD | EM | LM |
|---------|----|----|----|
| block | building and exterior walls | Building, WallSurface; property sets replaced | LOD1 block from the walls |
| envelope | plus roof, slabs, footings | plus RoofSurface, GroundSurface | LOD2, roof footprint |
| openings | plus storeys, windows, doors, stairs | plus Window, Door, BuildingInstallation | LOD3 |
| interior | everything, with property formatting | the full rule set, Room and InteriorWallSurface included | LOD4, rooms as solids |

Eighteen folders are placed by an `origin` and a `rotation` in their CM stage;
`20_box_interior` maps an IFC4 file that carries its own `IfcMapConversion` in
EPSG:5186, so its CM stage names no origin at all.

Input data and the pipeline config live under `input_data/`; **all** results
(intermediate + final) are written under `output/`. These are the defaults, so a
bare command runs the shipped example end to end:

```powershell
python B2GM_main.py
```

From a clone you can also use the launcher scripts, which find a Python, install
the core dependencies on first use and pass any extra arguments through:

| | Windows | Linux / macOS |
|---|---------|---------------|
| pipeline | `run_pipeline.bat` | `./run_pipeline.sh` |
| web view | `run_web.bat` | `./run_web.sh` |

```powershell
run_pipeline.bat --citygml-version 3.0
```

```bash
./run_pipeline.sh --citygml-version 3.0
PYTHON=/path/to/python ./run_web.sh --port 9000
```

Set `PYTHON` to pick a specific interpreter; otherwise `py -3` / `python3` is
used.

Equivalent explicit form:

```powershell
python B2GM_main.py --input input_data/duplex_apartment.ifc `
                    --pipeline input_data/B2GM_example.json `
                    --output-dir output
```

`python B2GM_main.py --help` lists every option and shows worked examples.

| Option         | Default                            | Meaning                                            |
|----------------|------------------------------------|----------------------------------------------------|
| `--input`      | `input_data/duplex_apartment.ifc`  | Source IFC (BIM) file                              |
| `--pipeline`   | `input_data/B2GM_example.json`     | Mapping pipeline JSON config                       |
| `--output-dir` | `output`                           | Directory for every intermediate and final result |
| `--output`     | `city.gml`                         | Final CityGML filename (written under `--output-dir`) |

Outputs written to `output/` (filenames come from the pipeline file):

- `intermediate.ifc`      + `intermediate.ifc.pd.json`  — PD perspective (selected elements)
- `intermediate_CM.ifc`   + `intermediate_CM.ifc.cm.json` — CM georeferencing summary (origin, true north, destination CRS, elements placed)
- `city.gml`              — EM result (CityGML 2.0)
- `city_LoD.gml`          — LM result (CityGML 2.0, LoD recorded as a generic
  attribute; where a rule carries an `operation`, the geometry is the operator
  result — the shipped example gives the building a LOD1 block and every room
  its own)

Both are **schema-valid CityGML** — the shipped example validates against the
official OGC schemas at `schemas.opengis.net`, in 2.0 and in 3.0. The BIM parser extracts each
element's triangulated geometry (via ifcopenshell's geometry engine) and the GIS
side writes a `gml:Envelope` plus a properly nested feature tree. IFC type,
GUID, the B2GM LoD name and every property-set value are preserved as
`gen:stringAttribute` generic attributes, so no element is lost.

### Choosing the CityGML version

The output schema is a variable, not a build-time choice:

```powershell
python B2GM_main.py --citygml-version 3.0
```

| Where | How |
|-------|-----|
| CLI | `--citygml-version {2.0,3.0}` on `b2gm`, `b2gm-em`, `b2gm-lm` |
| Pipeline file | `"citygml_version": "3.0"` next to `"BIM_GIS_mapping.pipeline"` |
| Single stage | `"citygml_version": "3.0"` inside an EM or LM stage |

Precedence is CLI, then the stage, then the pipeline file, then `2.0`. Both
versions come out of the same PD/CM/EM/LM result, so only the writer changes.

**CityGML 3.0 removes the storey limitation.** 2.0 has no feature for a building
storey, so `IfcBuildingStorey` can only survive as a generic attribute; 3.0 has
`bldg:Storey`, and the sample's four storeys become real features:

| EM destination | CityGML 2.0 | CityGML 3.0 |
|----------------|-------------|-------------|
| `BuildingStorey` | *(generic attribute only)* | `bldg:buildingSubdivision` → `bldg:Storey` |
| `Room` | `bldg:interiorRoom` → `bldg:Room` (lod4) | `bldg:buildingRoom` → `bldg:BuildingRoom` |
| `Window` / `Door` | `bldg:opening` → `bldg:Window` / `bldg:Door` | `con:fillingSurface` → `con:WindowSurface` / `con:DoorSurface` |
| `WallSurface`, … | `bldg:boundedBy` → `bldg:WallSurface` | `core:boundary` → `con:WallSurface` |
| `LandUse` | `luse:LandUse` (2.0) | `luse:LandUse` (3.0) |
| `BuildingStorey` contents | *(no hierarchy)* | rooms / surfaces / installations nested in their storey |
| geometry | GML 3.1.1, `gml:MultiSurface` | GML 3.2, `gml:Solid` when the mesh closes |

Two further 3.0 differences the writer handles: there is no LOD4 (levels are
clamped to LOD3) and `AbstractSpace` has no `lod1MultiSurface`, so an open mesh
tagged LOD1 is written at LOD2. A closed mesh — which is what the LM `extrude`
operator produces — is written as a `gml:Solid` at its own LoD, checked by
testing that every triangle edge is shared by exactly two faces.

`con:Window` and `con:Door` in 3.0 are *spaces* (physical objects), not the
surfaces filling a wall; the writer maps IFC openings to `con:WindowSurface` /
`con:DoorSurface`, which is what `con:fillingSurface` accepts.

**The IFC spatial hierarchy is preserved.** `IfcRelContainedInSpatialStructure`
records which storey holds each element, and a `bldg:Storey` can carry its own
rooms, installations and boundary surfaces, so the elements are written inside
their storey rather than flat under the building:

```
bldg:Building
  core:boundary            -> surfaces belonging to no storey
  core:lod1Solid           -> the LM block
  bldg:buildingSubdivision -> bldg:Storey "Level 1"
                                core:boundary            21 WallSurface, 10 FloorSurface, 5 CeilingSurface
                                bldg:buildingInstallation 4
                                bldg:buildingRoom        10 BuildingRoom
```

Set `"nest_by_storey": false` in the stage to keep everything flat under the
building instead.

The 3.0 element names, namespaces and child order are read from the CityGML 3.0
XSD bindings in [`citygml_parser.py`](citygml_parser.py) rather than hand-typed.

### CityGML document structure

Each EM destination is placed where the CityGML 2.0 content model expects it:

| EM destination | CityGML property | Feature | Geometry property |
|----------------|------------------|---------|-------------------|
| `CityModel.Building` | `core:cityObjectMember` | `bldg:Building` | `bldg:lod1MultiSurface` (LOD0/1) or `lod2MultiSurface` |
| `WallSurface`, `RoofSurface`, `GroundSurface`, `FloorSurface`, `CeilingSurface`, … | `bldg:boundedBy` | `bldg:WallSurface`, … | `bldg:lod2MultiSurface` (`lod3` when it hosts openings) |
| `Window`, `Door` | `bldg:opening` **of the host surface** | `bldg:Window` / `bldg:Door` | `bldg:lod3MultiSurface` |
| `Room` | `bldg:interiorRoom` | `bldg:Room` | `bldg:lod4MultiSurface` |
| `BuildingInstallation` | `bldg:outerBuildingInstallation` | `bldg:BuildingInstallation` | `bldg:lod2Geometry` |
| `IntBuildingInstallation` | `bldg:interiorBuildingInstallation` | `bldg:IntBuildingInstallation` | `bldg:lod4Geometry` |
| `BuildingPart` | `bldg:consistsOfBuildingPart` | `bldg:BuildingPart` | `bldg:lod2MultiSurface` |
| `LandUse` | `core:cityObjectMember` | `luse:LandUse` | `luse:lod1MultiSurface` |
| `GenericCityObject`, anything unmapped | `core:cityObjectMember` | `gen:GenericCityObject` | `gen:lod1Geometry` |

Windows and doors are attached to the wall they actually sit in: IFC records
`wall -voids-> opening` and `window -fills-> opening`, and the two chain through
the opening's GUID (36 of the 38 openings in the sample resolve; the rest are
written as installations rather than dropped). Because `bldg:opening` is only
allowed from LOD3, a surface that hosts openings is written at
`lod3MultiSurface`.

Children are emitted in the order `AbstractBuildingType` declares — geometry,
`outerBuildingInstallation`, `boundedBy`, `interiorRoom`,
`consistsOfBuildingPart` — since XSD sequences are order-sensitive, and every
`gml:id` is made unique within the document.

> **CityGML 2.0 has no storey feature**, so in 2.0 output `IfcBuildingStorey`
> elements (which carry no geometry) survive only as generic attributes of the
> building. Run with `--citygml-version 3.0` to get real `bldg:Storey` features.

> The geometry is written as `gml:MultiSurface`, not `gml:Solid` — the IFC
> triangulation is not guaranteed to close into a validated solid.

A stage's `output` in the pipeline JSON is treated as a bare filename and
re-rooted at `--output-dir`, so the source tree stays clean.

Each stage is also runnable stand-alone, e.g.:

```powershell
python B2GM_element.py --input input_data/duplex_apartment.ifc --output output/city.gml --option input_data/B2GM_example.json
```
