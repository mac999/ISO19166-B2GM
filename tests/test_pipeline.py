"""End-to-end tests for the full B2GM pipeline (PD -> CM -> EM -> LM)."""

import json
import os
import xml.etree.ElementTree as ET

import pytest

import B2GM_main as MAIN


def _pipeline_file(tmp_path):
    """Write a pipeline whose stage outputs live inside tmp_path."""
    pipeline = {
        "BIM_GIS_mapping.pipeline": [
            {
                "type": "PD",
                "output": str(tmp_path / "intermediate.ifc"),
                "data_view": [{"class": "IfcBuilding", "filter": [{"name": ".*", "value": ".*", "type": ".*"}]}],
                "logic_view": "",
                "style_view": [],
            },
            {
                "type": "CM",
                "output": str(tmp_path / "intermediate_CM.ifc"),
                "rule": [{"source": "EPSG:4326", "destination": "EPSG:3857"}],
            },
            {
                "type": "EM",
                "output": str(tmp_path / "city.gml"),
                "rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"}],
            },
            {
                "type": "LM",
                "output": str(tmp_path / "city_LoD.gml"),
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
    context = MAIN.mapping_ifc_to_target(sample_ifc, str(tmp_path / "city.gml"), pipeline_file)
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

    buildings = [el for el in root.iter() if local(el.tag) == "CityModel.Building"]
    assert len(buildings) == 1
    lods = [el.text for el in root.iter() if local(el.tag) == "lod"]
    assert lods == ["LOD1"]


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
