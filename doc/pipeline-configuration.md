# Pipeline configuration

`B2GM_example.json` defines the stage sequence. A stage carries its `type`
(`PD`/`CM`/`EM`/`LM`), an `output` filename and stage-specific rules:

```json
{ "type": "EM", "output": "city.gml",
  "rule": [{ "source": "IfcBuilding", "destination": "CityModel.Building" }] }
```

`source` / `class` patterns are **full-match** regular expressions, so
`IfcBuilding` does **not** match `IfcBuildingStorey` (use `.*Wall.*` for
substring matching).

### Full-element mapping

The shipped `input_data/B2GM_example.json` maps **every** element of the input
IFC to an appropriate CityGML feature — not just the building. Its PD `data_view`
selects all classes (`class: ".*"`) so nothing is dropped before element
mapping, and the EM stage carries one rule per IFC type, evaluated top-down
(**first full-match wins**) with a trailing `.*` catch-all so no element is ever
lost.

The BIM parser also exposes each element's IFC `PredefinedType`, so a rule can
**refine a type by its predefined kind** using a compound source
`<ifc_type>.<PredefinedType>` (e.g. `IfcSlab\.ROOF`); a plain `IfcSlab` rule
still matches every slab, and the ordering (specific before generic) resolves
the rest:

| IFC type (source) | CityGML feature |
|-------------------|-----------------|
| `IfcBuilding` | `CityModel.Building` |
| `IfcBuildingStorey` | `BuildingStorey` |
| `IfcSpace` | `Room` |
| `IfcWall`, `IfcWallStandardCase` (`IfcWall.*`) | `WallSurface` |
| `IfcSlab\.ROOF` | `RoofSurface` |
| `IfcSlab\.FLOOR`, `IfcSlab\.LANDING`, `IfcSlab` *(generic)* | `FloorSurface` |
| `IfcSlab\.BASESLAB` | `GroundSurface` |
| `IfcWindow` | `Window` |
| `IfcDoor` | `Door` |
| `IfcCovering\.CEILING` | `CeilingSurface` |
| `IfcCovering\.FLOORING` | `FloorSurface` |
| `IfcCovering`, `IfcBeam`, `IfcColumn`, `IfcMember`, `IfcRailing`, `IfcStair` | `BuildingInstallation` |
| `IfcSite` | `LandUse` |
| *(any other)* `.*` | `GenericCityObject` |

For the sample `duplex_apartment.ifc` this maps all **174** elements: 57
`WallSurface`, 24 `Window`, 21 `Room`, 20 `FloorSurface`, 18
`BuildingInstallation`, 14 `Door`, 13 `CeilingSurface`, 4 `BuildingStorey`, 1
`RoofSurface`, 1 `LandUse`, 1 `CityModel.Building` — the 21 slabs correctly
split into 20 floors + 1 roof, and the 13 ceiling coverings into
`CeilingSurface`.

## Coordinate mapping and georeferencing

The CM stage reads the IFC georeferencing (`IfcSite.RefLatitude` /
`RefLongitude` / `RefElevation` and the context `TrueNorth`) and **rewrites every
element's coordinates into the destination CRS**, so the emitted CityGML is
georeferenced rather than sitting at the project origin:

```json
{ "type": "CM", "output": "intermediate_CM.ifc",
  "rule": [
    { "source": "EPSG:4326", "destination": "EPSG:3857" },
    { "transform_matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]] }
  ] }
```

The placement chain is: the stage's 4×4 `transform_matrix`, then the true-north
rotation (IFC `+Y` is project north), then a transverse-Mercator CRS centred on
the site origin — which makes the IFC's local metres directly usable as
projected coordinates — and finally pyproj into `destination`. Any CRS pyproj
knows works, so `EPSG:3857`, a UTM zone or a national grid such as `EPSG:5186`
are all valid destinations.

| Stage key | Meaning |
|-----------|---------|
| `rule[].source` / `.destination` | source (IFC georeference) and destination CRS |
| `rule[].transform_matrix` | 4×4 placement applied in local coordinates first |
| `rule[].origin` | `{"lon":…, "lat":…, "elevation":…}` — origin for an IFC with no `IfcSite` georeferencing |
| `georeference` | set to `false` to keep the model in local coordinates |

The destination CRS is written as `srsName` on the `gml:Envelope` and on every
`gml:MultiSurface`. Without georeferencing (no `IfcSite` data and no `origin`
override) the stage logs a warning, leaves the coordinates local and omits
`srsName` — the file is still valid CityGML, just not placed.

For the shipped `duplex_apartment.ifc` the result lands at lon −87.6394 /
lat 41.8744 (Chicago) with its ground footprint preserved: the 8.85 × 26.57 m
local model becomes an 11.87 × 35.76 m envelope in EPSG:3857, which is the
expected Web Mercator inflation of 1/cos(41.87°) = 1.343.

## Perspective Definition views

The PD stage runs all three ISO 19166 views, not just the data filter.

**`data_view`** selects elements by class and property filter (regex).

**`logic_view`** joins external data into the perspective. `external_data_source`
is a JSON (`{GUID: {...}}` or a list of records with a `GUID` key) or CSV file
with a `GUID` column; without an `ETL_module` the records are joined onto the
matching elements as a `PD_logic` property set. An `ETL_module` is
`"module:function"`, imported and called as `fn(objects, source)`:

```json
{ "type": "PD",
  "logic_view": { "external_data_source": "input_data/PD_logic_source.json",
                  "ETL_module": "" } }
```

**`style_view`** picks the classes whose properties are styled;
`property_style` carries the `PD_property_style` rules that do the formatting.
`category` and `property` are regex, and `formattingOperation` is a `|`-separated
chain:

```json
{ "type": "PD",
  "style_view": [{ "class": ".*" }],
  "property_style": [
    { "category": "PSet_Revit_Dimensions", "property": "Length|Area|Volume",
      "formattingOperation": "round:3" },
    { "category": "Pset_.*Common", "property": "Reference",
      "formattingOperation": "strip|upper" }
  ] }
```

| `formattingOperation` | Effect |
|-----------------------|--------|
| `upper` / `lower` / `title` / `strip` | string case and whitespace |
| `round:N` | round a number to N digits (`round:0` yields an int) |
| `scale:F` | multiply a number by F |
| `prefix:TEXT` / `suffix:TEXT` | wrap the value |
| `replace:OLD:NEW` | substring replacement |
| `format:SPEC` | Python `str.format` spec, e.g. `format:{:.1f} m` |
| `truncate:N` | keep the first N characters |

After `select()` the schema-conformant `PD_data_view` holds one `PD_element` per
selected element, carrying its `objectGUID` and its `PD_category` groups (one per
property set).

## EM property-set operation

`EM_rule.PSet_operation` (ISO 19166 Table 5) decides what reaches the GIS
element when a rule defines its own `property_set`:

```json
{ "source": "IfcBuilding", "destination": "CityModel.Building",
  "PSet_operation": "Append",
  "property_set": { "B2GM": { "source_standard": "ISO 19166 B2GM" } } }
```

| Value | Result |
|-------|--------|
| `Append` (default) | the rule's `property_set` plus the source IFC property sets |
| `Replace` | the source IFC property sets only — the rule's set is dropped |

The chosen sets are what the CityGML `gen:stringAttribute` list is built from.

## B2G LM geometry operators

`B2GM_LM_operators.py` is a general, dataset-agnostic implementation of the LOD
mapping operators defined in ISO 19166 (Table 8). All eleven operators of the
UML `LM_rule` are implemented and reachable from the pipeline config. Geometry
is represented with `shapely` polygons (2D) and a lightweight `Solid` (vertices
+ faces B-rep, 3D); only `numpy` and `shapely` are required.

| Operator | Signature (UML) | Notes |
|----------|-----------------|-------|
| `footprint` | `footprint(el)` | projection onto XY |
| `OBB` | `OBB(el)` | principal-component oriented box |
| `projection` | `projection(g, base)` | `base` in `XY/XZ/YZ` (and the reversed `YX/ZX/ZY` spellings) |
| `boundary` | `boundary(g, base)` | outline of the projected area |
| `extrude` | `extrude(g, v, height)` | plus `base_z`; MultiPolygon input yields one merged solid |
| `exterior` / `interior` | `exterior(g)` / `interior(g)` | outer shell / inner shells |
| `VOID` | `VOID(e)` | window/door/opening sub-elements |
| `union` / `subtract` / `intersect` | `union(g1, g2)` … | 2D via shapely; 3D via `manifold3d` when installed (`pip install ".[mesh]"`), otherwise on vertical prisms (the LOD1 case) |

```python
from shapely.geometry import Polygon
import B2GM_LM_operators as OP

footprint = Polygon([(0, 0), (10, 0), (10, 20), (0, 20)])
block = OP.extrude(footprint, (0, 0, 1), height=12.0)   # LOD1 block model
block.save_obj("building.obj")                           # no pyvista/meshio needed

OP.footprint(block).area        # 200.0  (projection onto XY)
OP.projection(block, "XZ").area # 120.0  (elevation)
OP.obb(block).extent            # (20.0, 12.0, 10.0)  oriented bounding box
OP.union(a2d, b2d)              # 2D boolean set operators
OP.void(wall_element)           # window/door/opening sub-elements
```

Operators accept the flat `{'verts': [...], 'faces': [...]}` B-rep the IFC
parser attaches to every element, a `Solid`, or a shapely geometry;
`OP.from_brep()` / `OP.to_brep()` convert between the two.

3D booleans go through `manifold3d`, which is a mesh library rather than a CAD
kernel: it has no NURBS or filleting, but it guarantees a manifold result and is
a 1.9 MB wheel with no dependency beyond numpy. The meshes are handed over as
`Mesh64`, because after the CM stage the coordinates are in the destination CRS
and single precision resolves to about a metre there, which would erase a 54 mm
wall outright.

### Driving the operators from the pipeline

An `LM_rule` may carry an `operation`: a chain of operators applied to the
matched element. The first step receives the element, each later step the
previous result, and the final geometry replaces the element's own in the
CityGML output:

```json
{ "type": "LM", "output": "city_LoD.gml",
  "rule": [
    { "source": "IfcBuilding", "lod": "LOD1",
      "aggregate": "IfcWall.*|IfcSlab|IfcCovering",
      "operation": [
        { "op": "footprint" },
        { "op": "extrude",
          "args": { "v": [0, 0, 1], "height": {"$extent": "z"}, "base_z": {"$min": "z"} } }
      ] },
    { "source": "IfcSlab\\.ROOF", "lod": "LOD0", "operation": [{"op": "footprint"}] },
    { "source": ".*", "lod": "LOD2" }
  ] }
```

| Rule key | Meaning |
|----------|---------|
| `operation` | operator chain (`{"op": name, "args": {...}}`; a bare string is the operator name) |
| `aggregate` | regex over IFC types — run the chain on the merged geometry of every match instead of the element's own. An `IfcBuilding` carries no geometry, so its LOD1 block comes from its walls and slabs |

Argument values may reference the element instead of being literals:

| Reference | Resolves to |
|-----------|-------------|
| `{"$property": "Pset.Name"}` | a property-set value (coerced to float when possible) |
| `{"$extent": "z"}` | the element's bounding-box size along an axis |
| `{"$min": "z"}` / `{"$max": "z"}` | the low / high bound along an axis |

A failing chain is logged and the element keeps its source geometry, so one bad
rule never aborts the run.

A 2D result (`footprint`, `projection`, a boolean) carries no elevation, so it is
placed at the source element's own base rather than dropping to `z = 0` — a
`LOD0` roof footprint stays at roof height.

Pick the `aggregate` pattern to match the envelope you want: the shipped example
uses `IfcWall.*` rather than also taking `IfcSlab`, because the sample's entrance
terraces are slabs reaching 6 m beyond each end of the building and would stretch
the LOD1 block from 23.96 m to 35.76 m.

### Side utility: bulk footprint extrusion

`B2GM_LM_op_extrude.py` reuses the `extrude` operator over a set of GeoJSON
footprints (GeoJSON in, OBJ/CSV out), configured the same way as the pipeline.
It is a convenience script, not one of the B2GM stages.

```powershell
python B2GM_LM_op_extrude.py          # runs the bundled 100-footprint sample
python B2GM_LM_op_extrude.py --help   # every config key
```
