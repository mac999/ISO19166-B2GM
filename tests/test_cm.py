"""Tests for the Coordinate Mapping (CM) stage."""

import pytest

import B2GM_CM as CM


def test_dms_to_deg_positive():
    # 41 deg 52' 27.84" -> 41.8744
    assert CM.dms_to_deg((41, 52, 27, 840000)) == pytest.approx(41.8744, abs=1e-4)


def test_dms_to_deg_negative_sign_propagates():
    # -87 deg 38' 21.84" -> -87.6394
    val = CM.dms_to_deg((-87, -38, -21, -839999))
    assert val == pytest.approx(-87.6394, abs=1e-4)
    assert val < 0


def test_transform_coordinate_wgs84_to_webmercator():
    x, y = CM.transform_coordinate(-87.6394, 41.8744, "EPSG:4326", "EPSG:3857")
    # Chicago in Web Mercator (meters)
    assert x == pytest.approx(-9_755_970, abs=2000)
    assert y == pytest.approx(5_142_180, abs=2000)


def test_coordinate_mapping_from_stage_handles_typo():
    stage = {
        "rule": [
            {"source": "EPSG:4326", "destination": "EPSG:3857"},
            {"tranform_matrix": [[1, 0, 0, 0]]},  # original misspelled key
        ]
    }
    cm = CM.CoordinateMapping.from_stage(stage)
    assert cm.source_crs == "EPSG:4326"
    assert cm.dest_crs == "EPSG:3857"
    assert cm.transform_matrix == [[1, 0, 0, 0]]


def test_read_ifc_origin_and_apply(sample_ifc):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    ifc = ifcopenshell.open(sample_ifc)

    origin = CM.read_ifc_origin(ifc)
    assert origin is not None
    lon, lat, _elev = origin
    assert lat == pytest.approx(41.8744, abs=1e-3)
    assert lon == pytest.approx(-87.6394, abs=1e-3)

    cm = CM.CoordinateMapping("EPSG:4326", "EPSG:3857")
    summary = CM.apply_to_ifc(ifc, cm)
    assert summary["dest_origin"]["x"] == pytest.approx(-9_755_970, abs=5000)
