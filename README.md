# ISO 19166 B2GM — BIM to GIS conceptual Mapping

An implementation of the **ISO/TS 19166 B2GM** conceptual framework: mapping a
BIM model (IFC) into a GIS model (CityGML) through four well-defined stages.

```
 IFC (BIM)  ──►  PD  ──►  CM  ──►  EM  ──►  LM  ──►  CityGML (GIS)
                 │        │        │        │
        Perspective  Coordinate  Element    LoD
        Definition   Mapping     Mapping    Mapping
```

| Stage | Name                    | Purpose                                                        |
|-------|-------------------------|----------------------------------------------------------------|
| PD    | Perspective Definition  | Select the required subset of the BIM dataset (data/logic/style views) |
| CM    | Coordinate Mapping      | Transform source CRS → destination CRS (e.g. EPSG:4326 → EPSG:3857) |
| EM    | Element Mapping         | Map an IFC class to its GIS/CityGML class (e.g. `IfcBuilding` → `CityModel.Building`) |
| LM    | LoD Mapping             | Assign a GIS Level-of-Detail (LOD0…LOD4)                        |

See `doc/fig1.JPG` for the conceptual data model and mapping flow.

## Architecture

| Module                    | Role |
|---------------------------|------|
| `B2GM_model.py`           | Common conceptual data model (`element`, `geometry`, `property_set`, `property`, `relationship`, `LOD`, `model`) |
| `B2GM_BIM.py`             | BIM side — parses IFC into B2GM objects (tags each with a stable `ifc_type`) |
| `B2GM_GIS.py`             | GIS side — serialises mapped objects to a (simplified) CityGML XML file |
| `B2GM_PD.py`              | PD stage — perspective definition + element selection filters |
| `B2GM_CM.py`              | CM stage — CRS transforms (pyproj) + IFC georeference reading (DMS → degrees) |
| `B2GM_element.py`         | EM stage — element mapping rules (`source` → `destination`, `PSet_operation`) + CLI |
| `B2GM_LM.py`              | LM stage — LoD assignment rules + CLI |
| `B2GM_LM_operators.py`    | **B2G LM operator library** (ISO 19166 Table 8): `footprint`, `OBB`, `projection`, `boundary`, `extrude`, `exterior`, `interior`, `VOID`, `union`, `subtract`, `intersect` — numpy + shapely only |
| `B2GM_main.py`            | Pipeline orchestrator — runs PD → CM → EM → LM with a shared context |
| `B2GM_property.py`        | Property helpers over the conceptual model |
| `B2GM_LM_op_extrude.py`   | Footprint → LOD1 solid extrusion + OBJ/CSV export (config-driven); optional geopandas (read GeoJSON) / pyvista (view) |
| `B2GM_simple_mapping.py`  | Optional: strongly-typed CityGML output via xsdata dataclasses |

Optional heavy dependencies (`xsdata`, `geopandas`, `pyvista`, `pydeck`,
`meshio`) are imported lazily; the modules import and the core pipeline runs
without them (a clear error is raised only if an optional feature is invoked).

## Install

```powershell
pip install -r requirements.txt
```

## Run

```powershell
python B2GM_main.py --input sample_file/duplex_apartment.ifc --output city.gml --pipeline B2GM_example.json
```

Outputs (paths come from the pipeline file):

- `intermediate.ifc`      + `intermediate.ifc.pd.json`  — PD perspective (selected elements)
- `intermediate_CM.ifc`   + `intermediate_CM.ifc.cm.json` — CM georeferencing summary
- `city.gml`              — EM result (CityGML)
- `city_LoD.gml`          — LM result (CityGML with `<lod>` per element)

Each stage is also runnable stand-alone, e.g.:

```powershell
python B2GM_element.py --input sample_file/duplex_apartment.ifc --output city.gml --option B2GM_example.json
```

## Pipeline configuration

`B2GM_example.json` defines the stage sequence. A stage carries its `type`
(`PD`/`CM`/`EM`/`LM`), an `output` filename and stage-specific rules:

```json
{ "type": "EM", "output": "city.gml",
  "rule": [{ "source": "IfcBuilding", "destination": "CityModel.Building" }] }
```

`source` / `class` patterns are **full-match** regular expressions, so
`IfcBuilding` does **not** match `IfcBuildingStorey` (use `.*Wall.*` for
substring matching).

## B2G LM geometry operators

`B2GM_LM_operators.py` is a general, dataset-agnostic implementation of the LOD
mapping operators defined in ISO 19166 (Table 8). Geometry is represented with
`shapely` polygons (2D) and a lightweight `Solid` (vertices + faces B-rep, 3D);
only `numpy` and `shapely` are required.

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

Footprint extrusion for whole cities (GeoJSON in, OBJ/CSV out) is driven entirely
by the config file — footprint attribute names, storey height, base offset,
CRS transform and per-building colouring are all parameters, nothing is
hard-coded:

```powershell
python B2GM_LM_op_extrude.py LoD1_mapping_example.json         # extrude + export
python B2GM_LM_op_extrude.py LoD1_mapping_example.json --show  # 3D viewer (pyvista)
```

## Tests

```powershell
python -m pytest
```

The suite (`tests/`) covers the conceptual model, PD filtering, CM coordinate
transforms, EM/LM rule matching, GIS XML serialisation, IFC parsing and the
full end-to-end pipeline. Tests that need the sample IFC or optional
dependencies are skipped automatically when those are unavailable.

# Author
Taewook kang, Ph.D, laputa99999@gmail.com
