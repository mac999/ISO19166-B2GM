"""Tests for the generalised LoD extrude operator module."""

import os

import pytest
from shapely.geometry import Polygon

import B2GM_LM_op_extrude as EX
import B2GM_LM_operators as OP


def test_latlon_to_utm_zone_and_range():
    # Chicago ~ (41.87N, -87.63E) is UTM zone 16, northern hemisphere
    easting, northing, zone = EX.latlon_to_utm(41.8744, -87.6394)
    assert zone == 16
    assert 400_000 < easting < 500_000
    assert 4_600_000 < northing < 4_700_000


def test_extrude_polygon_returns_solid_without_pyvista():
    poly = Polygon([(0, 0), (10, 0), (10, 20), (0, 20), (0, 0)])
    solid = EX.extrude_polygon(poly, 12.0)
    assert isinstance(solid, OP.Solid)
    assert solid.volume() == pytest.approx(2400.0)  # 10*20*12


def test_extrude_polygon_base_offset_not_hardcoded():
    # regression: the old code subtracted magic offsets (4171084.25, 302905);
    # now the origin shift is exactly what the caller passes.
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    solid = EX.extrude_polygon(poly, 5.0, base_offset=(5, 5, 0))
    assert solid.vertices[:, 0].min() == pytest.approx(-5.0)
    assert solid.vertices[:, 1].min() == pytest.approx(-5.0)


def test_save_mesh_excel_writes_obj_and_csv(tmp_path):
    poly = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    solid = EX.extrude_polygon(poly, 3.0)
    features = [
        {"properties": {"BLDG_NM": "Terminal A", "GRO_FLO_CO": 3}, "geometry": [solid]},
        {"properties": {"BLDG_NM": "House"}, "geometry": [solid]},
    ]
    EX.save_mesh_excel(features, str(tmp_path))
    files = sorted(os.listdir(tmp_path))
    assert "building_1.obj" in files
    assert "building_2.obj" in files
    assert "building_properties.csv" in files
    # CSV header is the union of all property keys
    header = (tmp_path / "building_properties.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "BLDG_NM" in header and "GRO_FLO_CO" in header


def test_resolve_color_is_config_driven_not_hardcoded():
    rules = [
        {"property": "BLDG_NM", "match": "Terminal", "color": [1.0, 0.0, 0.0]},
        {"property": "BLDG_NM", "match": "Sports", "color": [0.0, 1.0, 0.0]},
    ]
    assert EX._resolve_color({"BLDG_NM": "Terminal A"}, rules) == (1.0, 0.0, 0.0)
    assert EX._resolve_color({"BLDG_NM": "Sports Center"}, rules) == (0.0, 1.0, 0.0)
    # no match -> a random RGB triple (never raises, never hardcoded)
    fallback = EX._resolve_color({"BLDG_NM": "Anything"}, rules)
    assert len(fallback) == 3 and all(0.0 <= c <= 1.0 for c in fallback)


def test_extrude_geojson_reads_without_geopandas(tmp_path):
    # GeoJSON reading falls back to json + shapely when geopandas is absent,
    # so a valid FeatureCollection extrudes without the optional dependency.
    import json

    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"BLDG_NM": "Terminal", "GRD_FL": 3, "UGR_FL": 1},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
            }
        ],
    }
    path = tmp_path / "footprints.geojson"
    path.write_text(json.dumps(gj), encoding="utf-8")

    features = EX.extrude_geojson(
        {"ground_storey": "GRD_FL", "underground_storey": "UGR_FL", "storey_height": 3.0},
        str(path),
    )
    assert len(features) == 1
    assert features[0]["properties"]["BLDG_NM"] == "Terminal"
    solid = features[0]["geometry"][0]
    assert isinstance(solid, OP.Solid)
    # (3 ground + 1 underground) * 3 m = 12 m tall over a 10x10 footprint
    assert solid.volume() == pytest.approx(1200.0)


# --- the shipped extrude example must actually run ---------------------------
def test_shipped_extrude_config_points_at_a_real_file():
    """README advertises a bare `python B2GM_LM_op_extrude.py`, so the config
    has to reference a file that exists and parses."""
    import json
    import os

    root = os.path.join(os.path.dirname(__file__), "..")
    config = json.load(open(os.path.join(root, "input_data", "LoD1_mapping_example.json"),
                            encoding="utf-8"))
    source = config["geometry"][0]["input"]
    path = os.path.join(root, source)
    assert os.path.isfile(path), f"{source} is missing"
    data = json.load(open(path, encoding="utf-8"))     # trailing commas would fail here
    assert data["features"], "the sample has no features"


def test_shipped_extrude_config_matches_the_sample_properties():
    """The storey attribute names in the config must exist on the features,
    otherwise every building silently falls back to the default height."""
    import json
    import os

    root = os.path.join(os.path.dirname(__file__), "..")
    config = json.load(open(os.path.join(root, "input_data", "LoD1_mapping_example.json"),
                            encoding="utf-8"))
    mapping = config["geometry"][0]
    data = json.load(open(os.path.join(root, mapping["input"]), encoding="utf-8"))
    properties = data["features"][0]["properties"]
    assert mapping["ground_storey"] in properties
    assert mapping["underground_storey"] in properties
    for style in config.get("style", []):
        assert style["property"] in properties
