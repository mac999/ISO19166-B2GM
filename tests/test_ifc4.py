"""The pipeline accepts IFC4 input, not only the IFC2X3 sample."""

import json
import os
import xml.etree.ElementTree as ET

import pytest

import B2GM_main as MAIN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IFC4_FILE = os.path.join(ROOT, "tests", "simple_ifc4.ifc")


def _local(tag):
    return tag.split("}")[-1]


def _pipeline_file(tmp_path):
    pipeline = {
        "BIM_GIS_mapping.pipeline": [
            {
                "type": "PD",
                "output": "intermediate.ifc",
                "data_view": [{"class": "Ifc.*", "filter": [{"name": ".*", "value": ".*", "type": ".*"}]}],
                "logic_view": "",
                "style_view": [],
            },
            {
                "type": "CM",
                "output": "intermediate_CM.ifc",
                "rule": [{"source": "EPSG:4326", "destination": "EPSG:3857"}],
            },
            {
                "type": "EM",
                "output": "city.gml",
                "rule": [
                    {"source": "IfcBuilding", "destination": "CityModel.Building"},
                    {"source": "IfcWall", "destination": "CityModel.Building.WallSurface"},
                ],
            },
            {
                "type": "LM",
                "output": "city_LoD.gml",
                "rule": [{"source": "IfcBuilding", "lod": "LOD1"}, {"source": "IfcWall", "lod": "LOD2"}],
            },
        ]
    }
    path = tmp_path / "pipeline.json"
    path.write_text(json.dumps(pipeline), encoding="utf-8")
    return str(path)


def test_fixture_is_ifc4():
    with open(IFC4_FILE, encoding="utf-8") as fh:
        head = fh.read(400)
    assert "FILE_SCHEMA(('IFC4'))" in head


def test_ifc4_runs_through_all_stages(tmp_path):
    pytest.importorskip("ifcopenshell")
    context = MAIN.mapping_ifc_to_target(
        IFC4_FILE, "city.gml", _pipeline_file(tmp_path), output_dir=str(tmp_path)
    )
    assert context["final_output"].endswith("city_LoD.gml")

    root = ET.parse(tmp_path / "city_LoD.gml").getroot()
    assert _local(root.tag) == "CityModel"
    buildings = [el for el in root.iter() if _local(el.tag) == "Building"]
    assert len(buildings) == 1
    polygons = [el for el in root.iter() if _local(el.tag) == "Polygon"]
    assert polygons, "wall geometry was dropped"

    # the fixture sits on IfcSite at 126.97E 37.55N, so CM must land it near
    # Seoul in web mercator rather than leaving it at the project origin
    first = next(el.text for el in root.iter() if _local(el.tag) in ("posList", "pos"))
    x, y = (float(v) for v in first.split()[:2])
    assert 1.41e7 < x < 1.42e7
    assert 4.50e6 < y < 4.53e6
