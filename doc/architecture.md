# Architecture and schema alignment

## Architecture

| Module                    | Role |
|---------------------------|------|
| `B2GM_model.py`           | Common conceptual data model (`element`, `geometry`, `property_set`, `property`, `relationship`, `LOD`, `model`) |
| `B2GM_BIM.py`             | BIM side — parses IFC into B2GM objects (tags each with a stable `ifc_type`) |
| `B2GM_GIS.py`             | GIS side — serialises mapped objects to a **renderable CityGML 2.0** file (geometry + `gml:Envelope`) |
| `B2GM_PD.py`              | PD stage — perspective definition + element selection filters |
| `B2GM_CM.py`              | CM stage — CRS transforms (pyproj), IFC georeference reading (DMS → degrees) and the `Placement` that moves the model into the destination CRS |
| `B2GM_element.py`         | EM stage — element mapping rules (`source` → `destination`, `PSet_operation`) + CLI |
| `B2GM_LM.py`              | LM stage — LoD assignment rules + CLI |
| `B2GM_LM_operators.py`    | **B2G LM operator library** (ISO 19166 Table 8): `footprint`, `OBB`, `projection`, `boundary`, `extrude`, `exterior`, `interior`, `VOID`, `union`, `subtract`, `intersect` — numpy + shapely only |
| `B2GM_main.py`            | Pipeline orchestrator — runs PD → CM → EM → LM with a shared context |
| `B2GM_property.py`        | Property helpers over the conceptual model |
| `B2GM_LM_op_extrude.py`   | Side utility: bulk GeoJSON footprint → LOD1 extrusion, outside the B2GM stages |
| `B2GM_simple_mapping.py`  | Optional: strongly-typed CityGML output via xsdata dataclasses |
| `B2GM_citygml3.py`        | CityGML **3.0** writer — restructured building model (real `bldg:Storey`, `con:fillingSurface` openings, GML 3.2), element names read from `citygml_parser.py` |
| `B2GM_web.py` + `web/`    | Web view — input tree + stage properties, WebGL 3D canvas, output tree (stdlib HTTP server, no extra dependency) |

Optional heavy dependencies (`xsdata`, `geopandas`, `pyvista`, `pydeck`,
`meshio`) are imported lazily; the modules import and the core pipeline runs
without them (a clear error is raised only if an optional feature is invoked).

## ISO 19166 schema alignment

The conceptual classes mirror the ISO 19166 UML structures shipped as XSD
schemas under [`XSD/`](../XSD/). Every `xs:complexType` maps to an implementation
class exposing each of its members:

| XSD schema | complexTypes → implementation |
|------------|-------------------------------|
| `B2GM_BIM_model.XSD` / `B2GM_GIS_model.XSD` | `BIM_element`/`GIS_element`, `BIM_model`/`GIS_model`, `property`, `property_set`, `relationship`, `runtime`, `geometry`, `geometry2D`, `geometry3D`, `B-rep`, `LOD` → `B2GM_model.py` |
| `B2GM_EM.XSD` | `EM_rule`, `EM_ruleset`, `EM_source`, `EM_destination` → `B2GM_element.py` |
| `B2GM_LM.XSD` | `LM_rule`, `LM_ruleset` → `B2GM_LM.py`; `OBB`, `vector3D` → `B2GM_LM_operators.py` |
| `B2GM_PD.XSD` | `PD`, `PD_data_view`, `PD_element`, `PD_category`, `PD_property`, `PD_logic_view`, `PD_property_style`, `PD_style_view` → `B2GM_PD.py` |

`tests/test_xsd_conformance.py` parses the XSDs directly and asserts that every
complexType member has a corresponding attribute on its class — so a missing or
renamed member is caught automatically.

### Saving the conceptual models as JSON

`B2GM_BIM.BIM.save()` and `B2GM_GIS.GIS.save()` serialise the parsed/mapped model
to JSON in the exact shape of `B2GM_BIM_model.XSD` / `B2GM_GIS_model.XSD`:

```python
objects = B2GM_BIM.BIM().parse("input_data/duplex_apartment.ifc")
B2GM_BIM.BIM().save("output/bim_model.json", objects)     # {"BIM_model": {"BIM_element": [...]}}

mapped = B2GM_element.apply(objects, rules)
B2GM_GIS.GIS().save("output/gis_model.json", mapped, stage)  # {"GIS_model": {"GIS_element": [...]}}
```

`BIM.load()` / `GIS.load()` read those JSON files back into the internal object
dicts, so a saved model can be re-mapped or re-serialised without touching the
IFC again — `save → load → save` is byte-identical:

```python
objects = B2GM_BIM.BIM().load("output/bim_model.json")     # same shape as parse()
gis_objs = B2GM_GIS.GIS().load("output/gis_model.json")    # restores _destination / _lod / geometry
B2GM_GIS.GIS().store("output/city.gml", gis_objs, {"rule": []})  # re-emit CityGML from JSON
```

A `BIM_element` carries `relationship` / `property_set` / `runtime` / `geometry`
(the element name + GUID become the mandatory *system* `property_set`, and
`geometry` holds the `B-rep` points/faces); a `GIS_element` carries `runtime`
(the mapped GIS class) / `LOD` (name + geometry) / `relationship` /
`property_set`. Run the whole pipeline with `--save-json` to emit both under the
output directory:

The parser also extracts inter-element **relationships** (ISO 19166 BM5/GM5) from
the IFC `IfcRel*` entities, mapping each to a UML relationship type — each record
is `{name, type, related}`:

| IFC relationship | `name` | UML `type` |
|------------------|--------|------------|
| `IfcRelAggregates` | `aggregates` | association |
| `IfcRelContainedInSpatialStructure` | `contains` | association |
| `IfcRelConnectsElements` / `…PathElements` | `connects` | association |
| `IfcRelVoidsElement` | `voids` | association |
| `IfcRelFillsElement` | `fills` | association |
| `IfcRelSpaceBoundary` | `space_boundary` | association |
| `IfcRelAssociatesMaterial` | `material` | dependency |
| `IfcRelDefinesByType` | `type` | generalization |

For `duplex_apartment.ifc` this yields 849 relationships across 245 elements
(association / dependency / generalization), carried through to the GIS model.

```powershell
python B2GM_main.py --save-json     # + output/bim_model.json, output/gis_model.json
```

`tests/test_model_json_save.py` checks the emitted JSON against the XSD members.
