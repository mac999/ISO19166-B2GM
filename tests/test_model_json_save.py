"""Tests for BIM.save / GIS.save - JSON serialisation per the ISO 19166 XSDs
(``B2GM_BIM_model.XSD`` / ``B2GM_GIS_model.XSD``)."""

import json
import os
import re

import pytest

import B2GM_element as EM
import B2GM_GIS as GIS

XSD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "XSD")


def _xsd_members(xsd_file, type_name):
    txt = open(os.path.join(XSD_DIR, xsd_file), "rb").read().decode("utf-16", "ignore")
    m = re.search(
        rf'<xs:complexType name="{re.escape(type_name)}">(.*?)</xs:complexType>', txt, re.S
    )
    return re.findall(r'<xs:element name="([^"]+)"', m.group(1)) if m else []


@pytest.fixture
def sample_objects():
    """Objects shaped like B2GM_BIM.BIM.parse() output (with geometry)."""
    return [
        {
            "name": "Basic Wall", "code": "Basic Wall", "ifc_type": "IfcWallStandardCase",
            "predefined_type": "", "type": "struct", "GUID": "wall-0001",
            "pset": {"Pset_WallCommon": {"IsExternal": "T", "Height": 3.0, "Count": 2}},
            "geometry": {"verts": [0, 0, 0, 1, 0, 0, 1, 0, 2], "faces": [0, 1, 2]},
        },
        {
            "name": "IfcSlab", "code": "IfcSlab", "ifc_type": "IfcSlab",
            "predefined_type": "ROOF", "type": "struct", "GUID": "slab-0001",
            "pset": {}, "geometry": None,
        },
    ]


# --- BIM.save --------------------------------------------------------------
def test_bim_save_matches_xsd(tmp_path, sample_objects):
    pytest.importorskip("ifcopenshell")
    import B2GM_BIM

    out = tmp_path / "bim.json"
    B2GM_BIM.BIM().save(str(out), sample_objects)
    doc = json.loads(out.read_text(encoding="utf-8"))

    assert "BIM_model" in doc
    elements = doc["BIM_model"]["BIM_element"]
    assert len(elements) == 2

    # BIM_element carries exactly the XSD members
    for key in _xsd_members("B2GM_BIM_model.XSD", "BIM_element"):
        assert key in elements[0], f"BIM_element missing XSD member {key}"

    # runtime.type is the IFC class; system property_set carries name + GUID
    assert elements[0]["runtime"]["type"] == "IfcWallStandardCase"
    sys_ps = elements[0]["property_set"][0]
    assert set(_xsd_members("B2GM_BIM_model.XSD", "property_set")) <= set(sys_ps)
    prop_names = {p["name"] for p in sys_ps["property"]}
    assert {"name", "GUID"} <= prop_names

    # a user property carries {name, type, value} and an inferred type
    user_ps = elements[0]["property_set"][1]
    height = next(p for p in user_ps["property"] if p["name"] == "Height")
    assert set(_xsd_members("B2GM_BIM_model.XSD", "property")) <= set(height)
    assert height["type"] == "real" and height["value"] == 3.0

    # geometry -> B-rep {points, faces}
    geom = elements[0]["geometry"]
    assert geom and "B-rep" in geom[0]
    brep = geom[0]["B-rep"][0]
    assert brep["points"] == [[0, 0, 0], [1, 0, 0], [1, 0, 2]]
    assert brep["faces"] == [[0, 1, 2]]
    # element without geometry serialises an empty list
    assert elements[1]["geometry"] == []


# --- GIS.save --------------------------------------------------------------
def test_gis_save_matches_xsd(tmp_path, sample_objects):
    rules_stage = {"rule": [
        {"source": "IfcWall.*", "destination": "WallSurface"},
        {"source": r"IfcSlab\.ROOF", "destination": "RoofSurface"},
    ]}
    mapped = EM.apply(sample_objects, EM.rules_from_stage(rules_stage))
    out = tmp_path / "gis.json"
    GIS.GIS().save(str(out), mapped, rules_stage)
    doc = json.loads(out.read_text(encoding="utf-8"))

    assert "GIS_model" in doc
    elements = doc["GIS_model"]["GIS_element"]
    assert len(elements) == 2

    for key in _xsd_members("B2GM_GIS_model.XSD", "GIS_element"):
        assert key in elements[0], f"GIS_element missing XSD member {key}"

    # runtime.type is the mapped GIS class; slab.ROOF refined to RoofSurface
    types = {e["runtime"]["type"] for e in elements}
    assert types == {"WallSurface", "RoofSurface"}

    # LOD carries {name, geometry} per XSD
    lod = elements[0]["LOD"][0]
    assert set(_xsd_members("B2GM_GIS_model.XSD", "LOD")) <= set(lod)
    assert lod["name"] == "LOD1"


def test_gis_save_skips_unmatched_when_rules_present(tmp_path, sample_objects):
    # a rule set that matches nothing -> no GIS elements written
    GIS.GIS().save(str(tmp_path / "empty.json"), sample_objects,
                   {"rule": [{"source": "IfcNope", "destination": "X"}]})
    doc = json.loads((tmp_path / "empty.json").read_text(encoding="utf-8"))
    assert doc["GIS_model"]["GIS_element"] == []


def test_bim_save_load_roundtrip(tmp_path, sample_objects):
    pytest.importorskip("ifcopenshell")
    import B2GM_BIM

    bim = B2GM_BIM.BIM()
    p1 = tmp_path / "bim1.json"
    p2 = tmp_path / "bim2.json"
    bim.save(str(p1), sample_objects)
    loaded = bim.load(str(p1))
    bim.save(str(p2), loaded)  # save -> load -> save must be identical

    assert len(loaded) == len(sample_objects)
    assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")
    # internal shape restored (same as parse output)
    wall = next(o for o in loaded if o["ifc_type"] == "IfcWallStandardCase")
    assert wall["GUID"] == "wall-0001"
    assert wall["pset"]["Pset_WallCommon"]["Height"] == 3.0
    assert wall["geometry"]["verts"] == [0, 0, 0, 1, 0, 0, 1, 0, 2]
    assert wall["geometry"]["faces"] == [0, 1, 2]


def test_gis_save_load_roundtrip(tmp_path, sample_objects):
    stage = {"rule": [
        {"source": "IfcWall.*", "destination": "WallSurface"},
        {"source": r"IfcSlab\.ROOF", "destination": "RoofSurface"},
    ]}
    mapped = EM.apply(sample_objects, EM.rules_from_stage(stage))
    gis = GIS.GIS()
    p1 = tmp_path / "gis1.json"
    p2 = tmp_path / "gis2.json"
    gis.save(str(p1), mapped, stage)
    loaded = gis.load(str(p1))
    gis.save(str(p2), loaded)  # no stage -> destination comes from _destination

    assert len(loaded) == len(mapped)
    assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")
    # mapping state restored
    wall = next(o for o in loaded if o["_destination"] == "WallSurface")
    assert wall["_lod"] == "LOD1"
    assert wall["geometry"]["verts"] == [0, 0, 0, 1, 0, 0, 1, 0, 2]
    # loaded objects can be re-serialised to CityGML
    n = gis.store(str(tmp_path / "rt.gml"), loaded, {"rule": []})
    assert n >= 1


def test_relationship_records_serialise(tmp_path):
    # objects carrying relationship records serialise per the XSD relationship shape
    objs = [{
        "name": "Wall", "ifc_type": "IfcWall", "GUID": "w1", "pset": {},
        "relationship": [
            {"name": "contains", "type": "association",
             "related": {"type": "IfcBuildingStorey", "guid": "s1", "name": "Level 1"}},
            {"name": "material", "type": "dependency",
             "related": {"type": "IfcMaterial", "guid": "", "name": "Concrete"}},
        ],
    }]
    pytest.importorskip("ifcopenshell")
    import B2GM_BIM

    B2GM_BIM.BIM().save(str(tmp_path / "rel.json"), objs)
    elem = json.loads((tmp_path / "rel.json").read_text(encoding="utf-8"))["BIM_model"]["BIM_element"][0]
    rels = elem["relationship"]
    assert len(rels) == 2
    # every relationship has the XSD members {name, type}
    for r in rels:
        assert set(_xsd_members("B2GM_BIM_model.XSD", "relationship")) <= set(r)
    assert {r["type"] for r in rels} == {"association", "dependency"}


# --- relationship extraction from a real IFC (integration) -----------------
@pytest.fixture
def parsed_with_relationships(sample_ifc):
    pytest.importorskip("ifcopenshell")
    import B2GM_BIM

    return B2GM_BIM.BIM().parse(sample_ifc)


def test_parser_extracts_relationships(parsed_with_relationships):
    import B2GM_model as M

    objs = parsed_with_relationships
    with_rel = [o for o in objs if o.get("relationship")]
    assert with_rel, "no relationships extracted from the sample IFC"

    all_rels = [r for o in objs for r in o.get("relationship", [])]
    # UML relationship types must be the ISO 19166 kinds
    valid = {M.RelationshipType.ASSOCIATION, M.RelationshipType.DEPENDENCY,
             M.RelationshipType.GENERALIZATION}
    assert {r["type"] for r in all_rels} <= valid
    # spatial decomposition / containment must be captured
    names = {r["name"] for r in all_rels}
    assert names & {"aggregates", "contains"}
    # each relationship references a target element/material/type
    assert all("related" in r and r["related"].get("type") for r in all_rels)
