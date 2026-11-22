"""A vertical CRS joins the horizontal one in srsName (EPSG:5186+5773)."""

import xml.etree.ElementTree as ET

import pytest

import B2GM_CM as CM
import B2GM_GIS as GIS
import B2GM_web


def test_compound_srs_joins_horizontal_and_vertical():
    assert CM.compound_srs("EPSG:5186", "EPSG:5773") == "EPSG:5186+5773"
    assert CM.compound_srs("EPSG:5186", "5773") == "EPSG:5186+5773"
    assert CM.compound_srs("EPSG:5186", None) == "EPSG:5186"
    assert CM.compound_srs("EPSG:5186", "") == "EPSG:5186"


def test_from_stage_reads_the_vertical_crs():
    stage = {"rule": [
        {"source": "EPSG:4326", "destination": "EPSG:5186", "vertical_crs": "EPSG:5773"},
    ]}
    mapping = CM.CoordinateMapping.from_stage(stage)
    assert mapping.dest_crs == "EPSG:5186"  # pyproj keeps the horizontal CRS
    assert mapping.vertical_crs == "EPSG:5773"


def test_from_stage_without_vertical_stays_none():
    stage = {"rule": [{"source": "EPSG:4326", "destination": "EPSG:5186"}]}
    assert CM.CoordinateMapping.from_stage(stage).vertical_crs is None


def test_placement_srs_name_is_compound():
    pytest.importorskip("pyproj")
    placement = CM.Placement((127.0, 37.5, 30.0), "EPSG:5186",
                             vertical_crs="EPSG:5773")
    assert placement.srs_name == "EPSG:5186+5773"
    # the transform itself still runs against the horizontal CRS
    x, y, z = placement.point(0.0, 0.0, 0.0)
    assert abs(z - 30.0) < 1e-9


def test_envelope_carries_the_compound_srs(tmp_path):
    out = tmp_path / "city.gml"
    objs = [{"name": "W", "ifc_type": "IfcWall", "GUID": "w1",
             "_destination": "WallSurface",
             "geometry": {"verts": [0, 0, 0, 1, 0, 0, 1, 0, 2], "faces": [0, 1, 2]}}]
    GIS.GIS().store(str(out), objs, {"rule": []}, srs_name="EPSG:5186+5773")
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    envelope = next(e for e in root.iter() if e.tag.endswith("Envelope"))
    assert envelope.get("srsName") == "EPSG:5186+5773"


def test_ground_scale_reads_the_horizontal_part():
    bounds = {"min": [14128000.0, 4509000.0, 0.0], "max": [14129000.0, 4510000.0, 10.0]}
    # web mercator still detected when compounded with a vertical CRS
    assert B2GM_web.ground_scale("EPSG:3857+5773", bounds) != 1.0
    # a metric CRS stays unscaled
    assert B2GM_web.ground_scale("EPSG:5186+5773", bounds) == 1.0
