"""A folder of building folders, each with its own pipeline, merged into one city model."""

import json
import os
import shutil
import xml.etree.ElementTree as ET

import pytest

import B2GM_batch as BATCH

HERE = os.path.dirname(os.path.abspath(__file__))
IFC4 = os.path.join(HERE, "simple_ifc4.ifc")


def _pipeline(lod, rotation, lon, lat, version="2.0"):
    return {
        "citygml_version": version,
        "BIM_GIS_mapping.pipeline": [
            {"type": "PD", "output": "intermediate.ifc",
             "data_view": [{"class": "Ifc.*", "filter": [{"name": ".*", "value": ".*", "type": ".*"}]}],
             "logic_view": "", "style_view": []},
            {"type": "EM", "output": "city.gml",
             "rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"},
                      {"source": "IfcWall", "destination": "WallSurface"}]},
            {"type": "LM", "output": "city_LoD_local.gml",
             "rule": [{"source": "IfcBuilding", "lod": lod, "aggregate": "IfcWall.*",
                       "operation": [{"op": "footprint"},
                                     {"op": "extrude", "args": {"height": {"$extent": "z"}}}]},
                      {"source": "IfcWall", "lod": "LOD2"}]},
            {"type": "CM", "output": "city_LoD.gml",
             "rule": [{"source": "EPSG:4326", "destination": "EPSG:5186"},
                      {"origin": {"lon": lon, "lat": lat, "elevation": 30.0}},
                      {"rotation": rotation}]},
        ],
    }


@pytest.fixture
def district(tmp_path):
    pytest.importorskip("ifcopenshell")
    pytest.importorskip("pyproj")
    root = tmp_path / "district"
    # building a: the fixture named by path; b: its own copy; c: nothing to run
    a = root / "01_a"
    a.mkdir(parents=True)
    (a / "pipeline.json").write_text(json.dumps(_pipeline("LOD1", 0.0, 127.0493, 37.5045) | {"input": IFC4}))
    b = root / "02_b"
    b.mkdir()
    shutil.copy(IFC4, b / "model.ifc")
    (b / "pipeline.json").write_text(json.dumps(_pipeline("LOD2", 90.0, 127.0631, 37.5088)))
    c = root / "03_c"
    c.mkdir()
    (c / "notes.json").write_text(json.dumps({"name": "not a pipeline"}))
    return root


def test_discover_finds_runnable_building_folders(district):
    entries = BATCH.discover(str(district))
    assert [e["name"] for e in entries] == ["01_a", "02_b"]
    assert entries[0]["ifc"] == IFC4
    assert entries[1]["ifc"].endswith("model.ifc")


def test_run_folder_maps_each_building_and_merges_them(district, tmp_path):
    out = tmp_path / "out"
    result = BATCH.run_folder(str(district), str(out))
    assert [e["name"] for e in result["entries"]] == ["01_a", "02_b"]
    assert (out / "01_a" / "city_LoD.gml").is_file() and (out / "02_b" / "city_LoD.gml").is_file()
    merged = result["merged"]
    assert merged == str(out / "district.gml") and os.path.isfile(merged)

    root = ET.parse(merged).getroot()
    local = lambda tag: tag.split("}")[-1]
    buildings = [el for el in root.iter() if local(el.tag) == "Building"]
    assert len(buildings) == 2
    ids = [el.get("{http://www.opengis.net/gml}id") for el in root.iter()
           if el.get("{http://www.opengis.net/gml}id")]
    assert len(ids) == len(set(ids)), "gml:ids collide across the two copies of one model"
    assert ids[0].startswith("b_01_a_") or ids[0].startswith("01_a") is False
    envelope = next(el for el in root.iter() if local(el.tag) == "Envelope")
    assert envelope.get("srsName") == "EPSG:5186"
    lower = [float(v) for v in envelope.find("{http://www.opengis.net/gml}lowerCorner").text.split()]
    upper = [float(v) for v in envelope.find("{http://www.opengis.net/gml}upperCorner").text.split()]
    # the two buildings sit about 1.3 km apart along Teheran-ro
    assert 1000 < upper[0] - lower[0] < 1600
    assert upper[2] - lower[2] == pytest.approx(3.0, abs=0.1)


def test_merge_refuses_mixed_citygml_versions(district, tmp_path):
    (district / "02_b" / "pipeline.json").write_text(
        json.dumps(_pipeline("LOD2", 0.0, 127.0631, 37.5088, version="3.0")))
    result = BATCH.run_folder(str(district), str(tmp_path / "out"))
    assert result["merged"] is None


def test_id_prefix_is_a_valid_ncname():
    assert BATCH._ncname("01_block") == "b_01_block"
    assert BATCH._ncname("Seolleung tower#2") == "Seolleung_tower_2"


def test_cm_rotation_turns_the_model_before_placing_it():
    import B2GM_CM as CM
    pytest.importorskip("pyproj")
    mapping = CM.CoordinateMapping.from_stage({"rule": [
        {"source": "EPSG:4326", "destination": "EPSG:5186"},
        {"origin": {"lon": 127.05, "lat": 37.505, "elevation": 0}},
        {"rotation": 90}]})
    placement = CM.Placement(mapping.origin, mapping.dest_crs, (0.0, 1.0), mapping.transform_matrix)
    ox, oy, _ = placement.point(0, 0, 0)
    x, y, _ = placement.point(10, 0, 0)       # local +X turned onto +Y: ten metres north
    assert abs(x - ox) < 0.01 and abs((y - oy) - 10) < 0.01
