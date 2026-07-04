"""Tests for the Element Mapping (EM) and LoD Mapping (LM) stages."""

import B2GM_element as EM
import B2GM_LM as LM


# --- Element Mapping -------------------------------------------------------
def test_element_rule_fullmatch(bim_objects):
    rule = EM.ElementRule("IfcBuilding", "CityModel.Building")
    building = bim_objects[0]
    storey = bim_objects[2]
    assert rule.matches(building)
    # full-match: IfcBuilding must not match IfcBuildingStorey
    assert not rule.matches(storey)


def test_predefined_type_refines_mapping():
    """A rule may target '<ifc_type>.<PredefinedType>' while a plain type rule
    still matches every element of that type (ISO 19166 EM refinement)."""
    roof_slab = {"ifc_type": "IfcSlab", "predefined_type": "ROOF", "name": "s1", "code": "s1"}
    floor_slab = {"ifc_type": "IfcSlab", "predefined_type": "FLOOR", "name": "s2", "code": "s2"}
    plain_slab = {"ifc_type": "IfcSlab", "predefined_type": "", "name": "s3", "code": "s3"}

    rules = EM.rules_from_stage(
        {
            "rule": [
                {"source": r"IfcSlab\.ROOF", "destination": "RoofSurface"},
                {"source": r"IfcSlab\.FLOOR", "destination": "FloorSurface"},
                {"source": "IfcSlab", "destination": "FloorSurface"},
            ]
        }
    )
    assert EM.map_element(roof_slab, rules) == "RoofSurface"
    assert EM.map_element(floor_slab, rules) == "FloorSurface"
    # a slab without a predefined type falls through to the generic slab rule
    assert EM.map_element(plain_slab, rules) == "FloorSurface"
    # the ROOF-specific rule must NOT match a FLOOR slab
    roof_only = [EM.ElementRule(r"IfcSlab\.ROOF", "RoofSurface")]
    assert EM.map_element(floor_slab, roof_only) is None


def test_map_element_returns_destination(bim_objects):
    rules = [EM.ElementRule("IfcBuilding", "CityModel.Building")]
    assert EM.map_element(bim_objects[0], rules) == "CityModel.Building"
    assert EM.map_element(bim_objects[1], rules) is None


def test_apply_tags_and_filters(bim_objects):
    rules = EM.rules_from_stage(
        {"rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"}]}
    )
    mapped = EM.apply(bim_objects, rules)
    assert len(mapped) == 1
    assert mapped[0]["_destination"] == "CityModel.Building"
    # source objects are not mutated
    assert "_destination" not in bim_objects[0]


def test_apply_wildcard_source(bim_objects):
    rules = EM.rules_from_stage({"rule": [{"source": ".*", "destination": "cityObject"}]})
    mapped = EM.apply(bim_objects, rules)
    assert len(mapped) == len(bim_objects)


# --- LoD Mapping -----------------------------------------------------------
def test_assign_lod_with_rule(bim_objects):
    rules = LM.rules_from_stage({"rule": [{"source": "IfcBuilding", "lod": "LOD2"}]})
    tagged = LM.assign_lod(bim_objects, rules)
    by_type = {o["ifc_type"]: o["_lod"] for o in tagged}
    assert by_type["IfcBuilding"] == "LOD2"
    # non-matching elements get the default LoD
    assert by_type["IfcWallStandardCase"] == LM.DEFAULT_LOD


def test_assign_lod_custom_default(bim_objects):
    tagged = LM.assign_lod(bim_objects, [], default_lod="LOD0")
    assert all(o["_lod"] == "LOD0" for o in tagged)


def test_lod_rule_destination_alias():
    rule = LM.LoDRule.from_dict({"source": "IfcBuilding", "destination": "LOD3"})
    assert rule.lod == "LOD3"


def test_lod1_from_footprint():
    from shapely.geometry import Polygon

    fp = Polygon([(0, 0), (10, 0), (10, 20), (0, 20)])
    solid = LM.lod1_from_footprint(fp, height=6.0)
    assert solid.volume() == 200.0 * 6.0


# --- EM PSet_operation (ISO 19166 Table 5) ---------------------------------
def test_element_rule_pset_operation_default_and_parse():
    default = EM.ElementRule.from_dict({"source": "IfcBuilding", "destination": "B"})
    assert default.pset_operation == EM.PSET_APPEND
    replace = EM.ElementRule.from_dict(
        {"source": "IfcBuilding", "destination": "B", "PSet_operation": "Replace"}
    )
    assert replace.pset_operation == EM.PSET_REPLACE


def test_apply_tags_pset_operation(bim_objects):
    rules = EM.rules_from_stage(
        {"rule": [{"source": "IfcBuilding", "destination": "B", "PSet_operation": "Replace"}]}
    )
    mapped = EM.apply(bim_objects, rules)
    assert mapped[0]["_pset_operation"] == "Replace"


def test_merge_psets_append_and_replace():
    dest = {"Common": {"A": 1, "B": 2}}
    src = {"Common": {"B": 9, "C": 3}, "Extra": {"X": 1}}

    appended = EM.merge_psets(dest, src, EM.PSET_APPEND)
    assert appended["Common"] == {"A": 1, "B": 9, "C": 3}
    assert appended["Extra"] == {"X": 1}

    replaced = EM.merge_psets(dest, src, EM.PSET_REPLACE)
    assert replaced == src
