"""End-to-end checks for the pipeline-driven ISO 19166 operators."""
import json
import os

import pytest
from shapely.geometry import Polygon

import B2GM_element as EM
import B2GM_LM as LM
import B2GM_LM_operators as OP
import B2GM_PD as PD

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture
def box_element():
    """A 4x3x2.5 box as the flat B-rep the BIM parser produces."""
    v = [0, 0, 0, 4, 0, 0, 4, 3, 0, 0, 3, 0,
         0, 0, 2.5, 4, 0, 2.5, 4, 3, 2.5, 0, 3, 2.5]
    f = [0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7,
         0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5,
         2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7]
    return {"ifc_type": "IfcSpace", "name": "Room", "GUID": "g1",
            "geometry": {"verts": v, "faces": f},
            "pset": {"Qto": {"Height": 2.5}}}


# --- operators read the parser's B-rep -------------------------------------
def test_operators_accept_flat_brep(box_element):
    assert OP.footprint(box_element).area == pytest.approx(12.0)
    assert OP.obb(box_element).extent == pytest.approx((4.0, 3.0, 2.5))


def test_plane_aliases(box_element):
    solid = OP.from_brep(box_element["geometry"])
    assert OP.projection(solid, "ZX").area == OP.projection(solid, "XZ").area


def test_to_brep_roundtrip(box_element):
    brep = OP.to_brep(OP.from_brep(box_element["geometry"]))
    assert len(brep["faces"]) % 3 == 0
    assert OP.from_brep(brep).volume() == pytest.approx(30.0)


# --- LM operator chains -----------------------------------------------------
def test_lm_rule_runs_operator_chain(box_element):
    rule = LM.LoDRule.from_dict({
        "source": "IfcSpace", "lod": "LOD1",
        "operation": [{"op": "footprint"},
                      {"op": "extrude", "args": {"height": {"$extent": "z"},
                                                 "base_z": {"$min": "z"}}}],
    })
    brep = rule.run_operation(box_element)
    assert OP.from_brep(brep).volume() == pytest.approx(30.0)


def test_assign_lod_attaches_geometry(box_element):
    rules = LM.rules_from_stage({"rule": [
        {"source": "IfcSpace", "lod": "LOD1", "operation": [{"op": "footprint"}]},
    ]})
    tagged = LM.assign_lod([box_element], rules)[0]
    assert tagged["_lod"] == "LOD1"
    assert len(tagged["_lod_geometry"]["faces"]) == 6  # 2 triangles


def test_operator_failure_is_non_fatal():
    rules = LM.rules_from_stage({"rule": [
        {"source": ".*", "lod": "LOD1", "operation": [{"op": "footprint"}]},
    ]})
    tagged = LM.assign_lod([{"ifc_type": "IfcBuilding"}], rules)[0]
    assert tagged["_lod"] == "LOD1" and "_lod_geometry" not in tagged


def test_aggregate_builds_geometry_from_parts(box_element):
    building = {"ifc_type": "IfcBuilding", "name": "B", "pset": {}}
    rules = LM.rules_from_stage({"rule": [
        {"source": "IfcBuilding", "lod": "LOD1", "aggregate": "IfcSpace",
         "operation": [{"op": "footprint"},
                       {"op": "extrude", "args": {"height": 10.0}}]},
    ]})
    tagged = LM.assign_lod([building, box_element], rules)[0]
    assert OP.from_brep(tagged["_lod_geometry"]).volume() == pytest.approx(120.0)


def test_resolve_arg_reads_properties(box_element):
    assert LM.resolve_arg({"$property": "Qto.Height"}, box_element) == 2.5
    assert LM.resolve_arg({"$extent": "x"}, box_element) == pytest.approx(4.0)
    assert LM.resolve_arg(3.0, box_element) == 3.0


# --- EM PSet_operation ------------------------------------------------------
def test_pset_operation_changes_output():
    obj = {"ifc_type": "IfcSpace", "pset": {"Pset_SpaceCommon": {"IsExternal": "F"}}}
    stage = {"rule": [{"source": "IfcSpace", "destination": "Room",
                       "PSet_operation": "Append",
                       "property_set": {"B2GM": {"stage": "EM"}}}]}
    appended = EM.apply([obj], EM.rules_from_stage(stage))[0]
    assert appended["pset"]["B2GM"] == {"stage": "EM"}
    assert "Pset_SpaceCommon" in appended["pset"]

    stage["rule"][0]["PSet_operation"] = "Replace"
    replaced = EM.apply([obj], EM.rules_from_stage(stage))[0]
    assert "B2GM" not in replaced["pset"]
    assert "Pset_SpaceCommon" in replaced["pset"]


# --- PD style / logic views -------------------------------------------------
def test_format_value_chain():
    assert PD.format_value(1.23456, "round:2") == 1.23
    assert PD.format_value("  a b ", "strip|upper") == "A B"
    assert PD.format_value(3, "scale:2|suffix: m") == "6.0 m"
    with pytest.raises(KeyError):
        PD.format_value(1, "nope")


def test_style_view_formats_selected_properties():
    perspective = PD.PerspectiveDefinition.from_stage({
        "data_view": [{"class": ".*"}],
        "style_view": [{"class": "IfcWall"}],
        "property_style": [{"category": "Qto", "property": "Length",
                            "formattingOperation": "round:1"}],
    })
    wall = {"ifc_type": "IfcWall", "GUID": "w", "pset": {"Qto": {"Length": 1.2345}}}
    slab = {"ifc_type": "IfcSlab", "GUID": "s", "pset": {"Qto": {"Length": 1.2345}}}
    perspective.select([wall, slab])
    assert wall["pset"]["Qto"]["Length"] == 1.2
    assert wall["_style"] == {"Qto.Length": 1.2}
    assert slab["pset"]["Qto"]["Length"] == 1.2345  # class not in the style view


def test_logic_view_joins_external_source(tmp_path):
    source = tmp_path / "extra.json"
    source.write_text(json.dumps({"g1": {"district": "Chicago"}}), encoding="utf-8")
    perspective = PD.PerspectiveDefinition.from_stage({
        "data_view": [{"class": ".*"}],
        "logic_view": {"external_data_source": str(source), "ETL_module": ""},
    })
    obj = {"ifc_type": "IfcBuilding", "GUID": "g1", "pset": {}}
    perspective.select([obj])
    assert obj["pset"]["PD_logic"] == {"district": "Chicago"}


def test_logic_view_runs_etl_module(tmp_path, monkeypatch):
    module = tmp_path / "etl_demo.py"
    module.write_text(
        "def run(objects, source):\n"
        "    for o in objects:\n"
        "        o.setdefault('pset', {})['ETL'] = {'seen': len(objects)}\n"
        "    return objects\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    perspective = PD.PerspectiveDefinition.from_stage({
        "data_view": [{"class": ".*"}],
        "logic_view": {"external_data_source": "", "ETL_module": "etl_demo:run"},
    })
    obj = {"ifc_type": "IfcSite", "GUID": "s1", "pset": {}}
    perspective.select([obj])
    assert obj["pset"]["ETL"] == {"seen": 1}


def test_pd_categories_are_populated():
    perspective = PD.PerspectiveDefinition.from_stage({"data_view": [{"class": ".*"}]})
    perspective.select([{"ifc_type": "IfcWall", "GUID": "w1",
                         "pset": {"Qto": {"Length": 1.0}}}])
    element = perspective.PD_data_view.PD_element[0]
    assert element.objectGUID == "w1"
    assert element.PD_category[0].name == "Qto"
    assert element.PD_category[0].PD_property[0].name == "Length"


# --- shipped example --------------------------------------------------------
def test_example_pipeline_uses_every_operator_hook():
    with open(os.path.join(HERE, "..", "input_data", "B2GM_example.json"),
              encoding="utf-8") as f:
        stages = json.load(f)["BIM_GIS_mapping.pipeline"]
    by_type = {s["type"]: s for s in stages}
    assert by_type["PD"]["property_style"]
    assert by_type["PD"]["logic_view"]["external_data_source"]
    assert any(r.get("property_set") for r in by_type["EM"]["rule"])
    assert any(r.get("operation") for r in by_type["LM"]["rule"])
    assert any(r.get("aggregate") for r in by_type["LM"]["rule"])


# --- CM georeferencing through the pipeline ---------------------------------
def test_gis_store_writes_srs_name(tmp_path):
    import B2GM_GIS

    objects = [{"name": "W", "GUID": "g", "_destination": "WallSurface",
                "geometry": {"verts": [0, 0, 0, 1, 0, 0, 1, 1, 0], "faces": [0, 1, 2]}}]
    path = str(tmp_path / "city.gml")
    B2GM_GIS.GIS().store(path, objects, {"rule": []}, srs_name="EPSG:3857")
    text = open(path, encoding="utf-8").read()
    assert 'srsName="EPSG:3857"' in text
    assert text.count('srsName="EPSG:3857"') >= 2   # envelope + geometry


def test_gis_store_omits_srs_name_when_local(tmp_path):
    import B2GM_GIS

    objects = [{"name": "W", "GUID": "g", "_destination": "WallSurface",
                "geometry": {"verts": [0, 0, 0, 1, 0, 0, 1, 1, 0], "faces": [0, 1, 2]}}]
    path = str(tmp_path / "local.gml")
    B2GM_GIS.GIS().store(path, objects, {"rule": []})
    assert "srsName" not in open(path, encoding="utf-8").read()


# --- footprint elevation ----------------------------------------------------
def test_footprint_keeps_the_element_elevation():
    """A 2D operator result carries no z, so it must stay at the element's base
    instead of dropping to the ground."""
    roof = {"ifc_type": "IfcSlab", "predefined_type": "ROOF",
            "geometry": {"verts": [0, 0, 6, 4, 0, 6, 4, 3, 6, 0, 3, 6.5],
                         "faces": [0, 1, 2, 0, 2, 3]}}
    rule = LM.LoDRule.from_dict({"source": ".*", "lod": "LOD0",
                                 "operation": [{"op": "footprint"}]})
    brep = rule.run_operation(roof)
    assert set(brep["verts"][2::3]) == {6.0}


def test_aggregate_uses_only_the_matching_types():
    """A too-wide aggregate pattern would swallow outlying slabs (terraces)."""
    wall = {"ifc_type": "IfcWall", "geometry": {"verts": [0, 0, 0, 4, 0, 0, 4, 3, 0],
                                                "faces": [0, 1, 2]}}
    terrace = {"ifc_type": "IfcSlab", "geometry": {"verts": [0, 20, 0, 4, 20, 0, 4, 25, 0],
                                                   "faces": [0, 1, 2]}}
    walls_only = LM.aggregate_geometry([wall, terrace], "IfcWall")
    both = LM.aggregate_geometry([wall, terrace], "IfcWall|IfcSlab")
    assert max(walls_only["verts"][1::3]) == 3.0
    assert max(both["verts"][1::3]) == 25.0
