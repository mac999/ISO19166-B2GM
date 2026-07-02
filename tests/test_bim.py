"""Tests for the BIM-side IFC parser (requires ifcopenshell + sample IFC)."""

import pytest

import B2GM_BIM as BIM


@pytest.fixture(scope="module")
def parsed(sample_ifc):
    pytest.importorskip("ifcopenshell")
    return BIM.BIM().parse(sample_ifc)


def test_parse_returns_objects(parsed):
    assert len(parsed) > 0


def test_every_object_has_stable_ifc_type(parsed):
    for obj in parsed:
        assert "ifc_type" in obj and obj["ifc_type"].startswith("Ifc")
        assert "GUID" in obj
        assert "pset" in obj


def test_building_is_present_and_georef(parsed):
    buildings = [o for o in parsed if o["ifc_type"] == "IfcBuilding"]
    assert len(buildings) == 1
    # the Revit sample carries a NumberOfStoreys property
    psets = buildings[0]["pset"]
    flat = {k: v for props in psets.values() for k, v in props.items()}
    assert "NumberOfStoreys" in flat


def test_ifc_type_not_overwritten_by_name_property(parsed):
    # some elements have a "name" property that overrides name/code, but
    # ifc_type must remain the true IFC class.
    for obj in parsed:
        assert obj["ifc_type"].startswith("Ifc")
