# ISO/TS 19166 traceability matrix

This matrix traces each normative element of ISO/TS 19166 (B2GM) to the code
that realises it and the tests that exercise it. The standard's UML structures
are shipped as XSD schemas under [`XSD/`](../XSD/); every row below can be
checked against those schemas and the test suite without access to the TS
text itself.

Scope note: this is a traceability matrix, not a conformance test suite. An
ISO 19105 executable test suite judges the *outputs of third-party
implementations* against the abstract test suite of the TS; nothing here
claims that. What the matrix shows is that this implementation realises every
schema member and behaviour the TS defines, each backed by an automated test.

`tests/test_xsd_conformance.py` is the mechanical anchor: it parses the XSDs
and asserts that every `xs:complexType` member has a corresponding attribute
on its implementation class, so a renamed or missing member fails the suite.

## 1. Conceptual models (B2GM BIM / GIS model)

| Standard element | Schema | Implementation | Tests |
|---|---|---|---|
| `BIM_model`, `BIM_element` | `B2GM_BIM_model.XSD` | `B2GM_model.model`, `B2GM_model.element`; parsed from IFC by `B2GM_BIM.BIM.parse` | `test_xsd_conformance.py`, `test_bim.py`, `test_model.py` |
| `GIS_model`, `GIS_element`, `LOD` | `B2GM_GIS_model.XSD` | `B2GM_model` classes; serialised by `B2GM_GIS.GIS.store`/`save` | `test_xsd_conformance.py`, `test_gis.py`, `test_model_json_save.py` |
| `property`, `property_set` (system property set: name + GUID, Table 1) | both model XSDs | `B2GM_model.property`, `property_set`, `system_property_set_json` | `test_model.py`, `test_model_json_save.py` |
| `relationship` (BM5/GM5 inter-element relations) | both model XSDs | `B2GM_BIM.BIM._attach_relationships` (`IfcRel*` to UML relationship types) | `test_bim.py`, `test_citygml3.py` (storey containment) |
| `geometry`, `geometry2D`, `geometry3D`, `B-rep` | both model XSDs | `B2GM_model.geometry*`, `brep`; tessellation in `B2GM_BIM` | `test_xsd_conformance.py`, `test_model_json_save.py` |
| `runtime` | both model XSDs | `B2GM_model.runtime` (carries the IFC type / mapped GIS class) | `test_xsd_conformance.py` |
| JSON serialisation in the exact XSD shape | both model XSDs | `BIM.save/load`, `GIS.save/load` (`save -> load -> save` is byte-identical) | `test_model_json_save.py` |

## 2. B2G PD - Perspective Definition

| Standard element | Schema | Implementation | Tests |
|---|---|---|---|
| `PD`, `PD_data_view`, `PD_element`, `PD_category`, `PD_property` | `B2GM_PD.XSD` | `B2GM_PD.PerspectiveDefinition` and rule classes | `test_xsd_conformance.py`, `test_pd.py` |
| `PD_logic_view` (external logic source / ETL module) | `B2GM_PD.XSD` | `B2GM_PD` logic-view evaluation | `test_pd.py` |
| `PD_sytle_view` [sic], `PD_property_style` | `B2GM_PD.XSD` | `B2GM_PD` style rules (drives the web-view property formatting) | `test_pd.py`, `test_web.py` |

## 3. B2G CM - Coordinate Mapping

| Standard element | Schema / behaviour | Implementation | Tests |
|---|---|---|---|
| source CRS to destination CRS transform | CM stage rules | `B2GM_CM.CoordinateMapping`, pyproj `Placement` | `test_cm.py` |
| IFC georeferencing: `IfcMapConversion` / `IfcProjectedCRS`, `IfcSite` lat/lon, true north, site placement, unit scale | IFC4 Add2 / IFC2x3 ePset convention | `read_map_conversion`, `read_ifc_origin`, `read_true_north`, `read_site_placement`, `length_unit_scale` | `test_cm.py` |
| stage-defined origin, rotation and 4x4 matrix | CM stage rules | `CoordinateMapping.from_stage`, `rotation_matrix`, `compose` | `test_cm.py` |
| compound horizontal + vertical CRS in `srsName` | CM `vertical_crs` key | `compound_srs`, `Placement.srs_name` | `test_vertical_crs.py` |
| CM placed before or after EM/LM (either order georeferences the output) | pipeline ordering | `B2GM_main.mapping_CM`, `apply_placement` | `test_pipeline.py`, `test_lm_local.py` |

## 4. B2G EM - Element Mapping

| Standard element | Schema | Implementation | Tests |
|---|---|---|---|
| `EM_rule`, `EM_ruleset`, `EM_source`, `EM_destination` (Table 6) | `B2GM_EM.XSD` | `B2GM_element.ElementRule`, `EM_ruleset` | `test_xsd_conformance.py`, `test_element_lm.py` |
| `PSet_operation`: Append / Update / Overwrite / Ignore (Table 5) | `B2GM_EM.XSD` | `B2GM_element.merge_psets` | `test_element_lm.py` |
| property filters on source elements (incl. `PredefinedType` refinement) | EM stage rules | `ElementRule._filters_match`, `matches` | `test_element_lm.py`, `test_full_element_mapping.py` |

## 5. B2G LM - LoD Mapping (Clause 9, Table 8)

| Operator (Table 8) | Implementation | Tests |
|---|---|---|
| `footprint(el)` | `B2GM_LM_operators.footprint` | `test_operators.py` |
| `OBB(el)` | `obb` | `test_operators.py` |
| `projection(g, plane)` | `projection` | `test_operators.py` |
| `boundary(g, plane)` | `boundary` | `test_operators.py` |
| `extrude(g2D, v, height)` | `extrude` | `test_operators.py`, `test_extrude.py` |
| `exterior(g)` | `exterior` | `test_operators.py` |
| `interior(g)` | `interior` | `test_operators.py` |
| `VOID(el)` | `void` | `test_operators.py` |
| `union / subtract / intersect` | `union`, `subtract`, `intersect` (manifold3d, prism fallback) | `test_operators.py` |
| `LM_rule`, `LM_ruleset`, `OBB`, `vector3D` structures | `B2GM_LM.LoDRule`, `LM_ruleset`, `B2GM_LM_operators.OBB`, `Vector3D` | `test_xsd_conformance.py`, `test_element_lm.py` |
| declarative operator chains with `aggregate` and `$extent/$property` args | `LoDRule.run_operation`, `run_chain`, `resolve_arg` | `test_operator_pipeline.py` |
| operators run in local metres when CM placed the model first | `assign_lod(placement=...)`, `apply_placement` local vertices | `test_lm_local.py` |

Implementation extensions beyond Table 8, named as such in the docs: the
`envelope` operator (watertight outer-shell union) with `semantic_surfaces`
(Roof/Wall/Ground split) and `consume` (`test_envelope.py`).

## 6. Pipeline and output

| Behaviour | Implementation | Tests |
|---|---|---|
| four-stage pipeline (PD/CM/EM/LM) in any order from one pipeline file | `B2GM_main.mapping_ifc_to_target` | `test_pipeline.py`, `test_ifc4.py` |
| CityGML 2.0 output (buildings, boundary surfaces, openings, rooms, installations, generics) | `B2GM_GIS` | `test_gis.py`, `test_citygml_structure.py` |
| CityGML 3.0 output (storeys, `core:boundary`, `con:fillingSurface`, solids) | `B2GM_citygml3` | `test_citygml3.py` |
| typed generic attributes (int / double / date beside string) | `B2GM_GIS.attribute_kind/attribute_text`, both writers | `test_typed_attributes.py` |
| IFC 4.3 infrastructure to the bridge / tunnel / transportation modules | writer `PLACEMENT` tables, `B2GM_BIM` (schema-agnostic parse) | `test_infra43.py` |
| solid validity (closure, orientation, degeneracy; val3dity hook) | `B2GM_validate` | `test_validity.py` |
| district batch: one pipeline per building folder, merged city model | `B2GM_batch` | `test_batch.py` |
| run record and final-output tracking | `B2GM_main.write_run_record` | `test_pipeline.py`, `test_web.py` |

## Known gaps

* `srsName` on the saved JSON models has no XSD member; the TS schemas define
  no CRS slot, so it is carried as an extra key (documented in
  [`doc/architecture.md`](../doc/architecture.md)).
* The LOD2 envelope is the fused material shell of the aggregated elements,
  not the gross building volume; openings in the fabric keep the interior
  connected to the outside.
* An ISO 19105 executable conformance suite (abstract test suite, test
  purposes, verdict criteria for third-party outputs) is future work and a
  separate deliverable from this matrix.
