"""End-to-end tests for the full B2GM pipeline (PD -> CM -> EM -> LM)."""

import json
import os
import xml.etree.ElementTree as ET

import pytest

import B2GM_main as MAIN


def _pipeline_file(tmp_path):
    """Write a pipeline whose stage outputs are bare filenames (re-rooted at output_dir)."""
    pipeline = {
        "BIM_GIS_mapping.pipeline": [
            {
                "type": "PD",
                "output": "intermediate.ifc",
                "data_view": [{"class": "IfcBuilding", "filter": [{"name": ".*", "value": ".*", "type": ".*"}]}],
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
                "rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"}],
            },
            {
                "type": "LM",
                "output": "city_LoD.gml",
                "rule": [{"source": "IfcBuilding", "lod": "LOD1"}],
            },
        ]
    }
    path = tmp_path / "pipeline.json"
    path.write_text(json.dumps(pipeline), encoding="utf-8")
    return str(path)


@pytest.fixture
def run_pipeline(tmp_path, sample_ifc):
    pytest.importorskip("ifcopenshell")
    pipeline_file = _pipeline_file(tmp_path)
    context = MAIN.mapping_ifc_to_target(
        sample_ifc, "city.gml", pipeline_file, output_dir=str(tmp_path)
    )
    return tmp_path, context


def test_pipeline_produces_all_stage_outputs(run_pipeline):
    tmp_path, _ = run_pipeline
    for name in ["intermediate.ifc", "intermediate_CM.ifc", "city.gml", "city_LoD.gml"]:
        assert (tmp_path / name).exists(), f"missing {name}"


def test_pipeline_final_output_is_valid_lod_citygml(run_pipeline):
    tmp_path, context = run_pipeline
    final = context["final_output"]
    assert final.endswith("city_LoD.gml")

    root = ET.fromstring((tmp_path / "city_LoD.gml").read_text(encoding="utf-8"))

    def local(tag):
        return tag.split("}")[-1]

    # CityGML 2.0: one bldg:Building plus a gml:Envelope
    assert local(root.tag) == "CityModel"
    buildings = [el for el in root.iter() if local(el.tag) == "Building"]
    assert len(buildings) == 1
    assert any(local(el.tag) == "Envelope" for el in root.iter())
    # LM result recorded as a generic attribute
    lods = [
        v.text
        for sa in root.iter()
        if local(sa.tag) == "stringAttribute" and sa.get("name") == "lod"
        for v in sa
        if local(v.tag) == "value"
    ]
    assert "LOD1" in lods


def test_pipeline_context_has_crs_and_perspective(run_pipeline):
    _, context = run_pipeline
    assert context["crs"]["dest_crs"] == "EPSG:3857"
    assert context["crs"]["dest_origin"] is not None
    # PD selected exactly the building
    assert len(context["perspective_guids"]) == 1


def test_pipeline_writes_sidecars(run_pipeline):
    tmp_path, _ = run_pipeline
    assert (tmp_path / "intermediate.ifc.pd.json").exists()
    cm_sidecar = tmp_path / "intermediate_CM.ifc.cm.json"
    assert cm_sidecar.exists()
    data = json.loads(cm_sidecar.read_text(encoding="utf-8"))
    assert data["source_crs"] == "EPSG:4326"


def test_pipeline_georeferences_the_output(tmp_path):
    """The CM stage must place the CityGML in the destination CRS."""
    import re

    import B2GM_main

    ifc = os.path.join(os.path.dirname(__file__), "..", "input_data",
                       "duplex_apartment.ifc")
    if not os.path.exists(ifc):
        pytest.skip("sample IFC not available")
    pytest.importorskip("pyproj")

    pipeline = tmp_path / "pipe.json"
    pipeline.write_text(json.dumps({"BIM_GIS_mapping.pipeline": [
        {"type": "CM", "output": "cm.ifc",
         "rule": [{"source": "EPSG:4326", "destination": "EPSG:3857"}]},
        {"type": "EM", "output": "city.gml",
         "rule": [{"source": ".*", "destination": "GenericCityObject"}]},
    ]}), encoding="utf-8")

    context = B2GM_main.mapping_ifc_to_target(ifc, "city.gml", str(pipeline), str(tmp_path))
    assert context["crs"]["elements_transformed"] > 0
    assert context["srs_name"] == "EPSG:3857"

    text = open(context["final_output"], encoding="utf-8").read(2000)
    assert 'srsName="EPSG:3857"' in text
    lower = [float(v) for v in re.search(r"lowerCorner>([^<]+)<", text).group(1).split()]
    # the sample sits in Chicago, so EPSG:3857 easting must be far negative
    assert lower[0] < -9_000_000 and 5_000_000 < lower[1] < 5_300_000


def test_cm_can_run_last_so_the_lod_geometry_is_built_in_local_metres(tmp_path):
    """PD -> EM -> LM -> CM: the operators work in the IFC's metres and the CM
    stage, placed last, projects the result and writes the final CityGML."""
    pytest.importorskip("ifcopenshell")
    pytest.importorskip("pyproj")
    ifc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "simple_ifc4.ifc")
    pipeline = {"BIM_GIS_mapping.pipeline": [
        {"type": "PD", "output": "intermediate.ifc",
         "data_view": [{"class": "Ifc.*", "filter": [{"name": ".*", "value": ".*", "type": ".*"}]}],
         "logic_view": "", "style_view": []},
        {"type": "EM", "output": "city.gml",
         "rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"},
                  {"source": "IfcWall", "destination": "WallSurface"}]},
        {"type": "LM", "output": "city_LoD_local.gml",
         "rule": [{"source": "IfcBuilding", "lod": "LOD1", "aggregate": "IfcWall.*",
                   "operation": [{"op": "footprint"},
                                 {"op": "extrude", "args": {"height": {"$extent": "z"}}}]},
                  {"source": "IfcWall", "lod": "LOD2"}]},
        {"type": "CM", "output": "city_LoD.gml",
         "rule": [{"source": "EPSG:4326", "destination": "EPSG:3857"}]},
    ]}
    path = tmp_path / "pipeline.json"
    path.write_text(json.dumps(pipeline), encoding="utf-8")
    context = MAIN.mapping_ifc_to_target(ifc, "city.gml", str(path), output_dir=str(tmp_path))
    assert context["final_output"].endswith("city_LoD.gml")

    def local(tag):
        return tag.split("}")[-1]

    def first_pos(root):
        text = next(el.text for el in root.iter() if local(el.tag) in ("posList", "pos"))
        return [float(v) for v in text.split()[:3]]

    # LM wrote its own output before CM ran: still in local metres, no CRS
    local_root = ET.parse(tmp_path / "city_LoD_local.gml").getroot()
    assert all(el.get("srsName") is None for el in local_root.iter())
    assert abs(first_pos(local_root)[0]) < 100

    # the CM stage wrote the final file, projected, same features
    final_root = ET.parse(tmp_path / "city_LoD.gml").getroot()
    assert any(el.get("srsName") == "EPSG:3857" for el in final_root.iter())
    assert 1.41e7 < first_pos(final_root)[0] < 1.42e7
    count = lambda root: sum(1 for el in root.iter() if local(el.tag) == "Polygon")
    assert count(final_root) == count(local_root) > 0
    # the LOD1 block keeps its local height: 3 m walls, z unscaled by the projection
    zs = [float(v) for el in final_root.iter() if local(el.tag) == "posList"
          for v in el.text.split()[2::3]]
    assert 2.9 < max(zs) - min(zs) < 3.1
