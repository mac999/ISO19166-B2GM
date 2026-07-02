"""Tests for the Perspective Definition (PD) stage."""

import B2GM_PD as PD


def test_filter_matches_regex():
    f = PD.Filter(name="Height", value=".*", data_type=".*")
    assert f.matches("Height", 3.0, "float")
    assert not f.matches("Width", 3.0, "float")


def test_filter_empty_pattern_is_permissive():
    f = PD.Filter(name="", value="", data_type="")
    assert f.matches("anything", 123, "int")


def test_dataview_class_fullmatch():
    dv = PD.DataView.from_dict({"class": "IfcBuilding", "filter": []})
    assert dv.class_matches("IfcBuilding")
    # full-match: must not match the longer storey / proxy classes
    assert not dv.class_matches("IfcBuildingStorey")
    assert not dv.class_matches("IfcBuildingElementProxy")


def test_perspective_from_stage_and_select(bim_objects):
    stage = {
        "data_view": [{"class": "IfcBuilding", "filter": [{"name": ".*", "value": ".*", "type": ".*"}]}],
        "logic_view": "./logic.exe",
        "style_view": [],
    }
    pd = PD.PerspectiveDefinition.from_stage(stage)
    assert pd.logic_view == "./logic.exe"

    selected = pd.select(bim_objects)
    names = {o["ifc_type"] for o in selected}
    assert names == {"IfcBuilding"}


def test_perspective_wildcard_selects_all(bim_objects):
    stage = {"data_view": [{"class": ".*", "filter": [{"name": ".*"}]}]}
    pd = PD.PerspectiveDefinition.from_stage(stage)
    selected = pd.select(bim_objects)
    assert len(selected) == len(bim_objects)


def test_perspective_property_value_filter(bim_objects):
    # select only elements that have an IsExternal == T property
    stage = {"data_view": [{"class": ".*", "filter": [{"name": "IsExternal", "value": "T", "type": ".*"}]}]}
    pd = PD.PerspectiveDefinition.from_stage(stage)
    selected = pd.select(bim_objects)
    assert [o["ifc_type"] for o in selected] == ["IfcWallStandardCase"]
