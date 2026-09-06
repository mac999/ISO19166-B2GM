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


# --- geometry placement (CM actually moves the model) ------------------------
import math

import pytest


def _placement(lon=-87.6394, lat=41.8744, elevation=0.0, **kwargs):
    return CM.Placement((lon, lat, elevation), "EPSG:3857", **kwargs)


def test_placement_puts_the_origin_on_the_site():
    place = _placement()
    x, y, z = place.point(0, 0, 0)
    expected = CM.transform_coordinate(-87.6394, 41.8744, "EPSG:4326", "EPSG:3857")
    assert (x, y) == pytest.approx(expected)
    assert z == 0.0


def test_placement_keeps_ground_distance_after_mercator_scale():
    place = _placement()
    origin = place.point(0, 0, 0)
    east = place.point(100.0, 0, 0)
    north = place.point(0, 100.0, 0)
    # Web Mercator inflates distance by 1/cos(lat); dividing it out returns metres.
    # EPSG:3857 projects geodetic latitude on a sphere, so ~0.2% remains.
    k = 1.0 / math.cos(math.radians(41.8744))
    assert (east[0] - origin[0]) / k == pytest.approx(100.0, rel=3e-3)
    assert (north[1] - origin[1]) / k == pytest.approx(100.0, rel=3e-3)


def test_placement_adds_the_site_elevation():
    assert _placement(elevation=12.5).point(0, 0, 3.0)[2] == pytest.approx(15.5)


def test_placement_applies_true_north_rotation():
    # true north along +X means the model's +X is north, so +X must move north
    rotated = _placement(true_north=(1.0, 0.0))
    origin = rotated.point(0, 0, 0)
    moved = rotated.point(100.0, 0, 0)
    assert moved[1] - origin[1] > 100.0      # northing grew
    assert moved[0] == pytest.approx(origin[0], abs=1e-6)


def test_placement_applies_the_transform_matrix():
    shifted = _placement(transform_matrix=[[1, 0, 0, 10], [0, 1, 0, 0],
                                           [0, 0, 1, 5], [0, 0, 0, 1]])
    plain = _placement()
    assert shifted.point(0, 0, 0)[0] == pytest.approx(plain.point(10, 0, 0)[0])
    assert shifted.point(0, 0, 0)[2] == pytest.approx(5.0)


def test_apply_placement_rewrites_element_geometry():
    objects = [
        {"geometry": {"verts": [0, 0, 0, 10, 0, 0], "faces": [0, 1, 0]}},
        {"name": "no geometry"},
    ]
    moved = CM.apply_placement(objects, _placement())
    assert moved == 1
    verts = objects[0]["geometry"]["verts"]
    assert len(verts) == 6 and verts[0] < -9_000_000     # now in EPSG:3857


def test_stage_reads_origin_override_and_switch():
    mapping = CM.CoordinateMapping.from_stage({
        "georeference": False,
        "rule": [{"source": "EPSG:4326", "destination": "EPSG:5186"},
                 {"origin": {"lon": 126.98, "lat": 37.56, "elevation": 20.0}}],
    })
    assert mapping.dest_crs == "EPSG:5186"
    assert mapping.origin == (126.98, 37.56, 20.0)
    assert mapping.georeference is False


def test_placement_works_for_a_projected_national_crs():
    # EPSG:5186 (Korea Central Belt 2010) - a metric CRS with no mercator inflation
    place = CM.Placement((126.9780, 37.5665, 0.0), "EPSG:5186")
    origin = place.point(0, 0, 0)
    east = place.point(100.0, 0, 0)
    assert east[0] - origin[0] == pytest.approx(100.0, rel=1e-3)
