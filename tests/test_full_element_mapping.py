"""Regression tests: the shipped input_data/B2GM_example.json must map *every*
element of the input IFC through element mapping (EM) into city.gml.

These guard against a config regressing back to a "building-only" perspective,
where PD/EM would silently drop walls, doors, windows, slabs, spaces, etc.
"""

import json
import os
import re

import pytest

import B2GM_main as MAIN

# The real, shipped pipeline config (not a synthetic fixture).
CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "input_data",
    "B2GM_example.json",
)


@pytest.fixture
def full_pipeline(tmp_path, sample_ifc):
    pytest.importorskip("ifcopenshell")
    if not os.path.exists(CONFIG):
        pytest.skip(f"pipeline config not available: {CONFIG}")
    context = MAIN.mapping_ifc_to_target(
        sample_ifc, "city.gml", CONFIG, output_dir=str(tmp_path)
    )
    city_gml = (tmp_path / "city.gml").read_text(encoding="utf-8")
    return context, city_gml


def _feature_types(city_gml):
    """Distinct CityGML feature/surface tags plus the semantic `gis_class`
    attribute values recorded on building installations."""
    surfaces = set(re.findall(r"<bldg:([A-Za-z]+Surface)\b", city_gml))
    gis_classes = set(
        re.findall(
            r'<gen:stringAttribute name="gis_class">\s*<gen:value>([^<]+)</gen:value>',
            city_gml,
        )
    )
    return surfaces | gis_classes


def test_em_drops_no_element(full_pipeline):
    context, _ = full_pipeline
    objects = context["objects"]
    mapped = context["em_mapped"]
    assert objects, "sample IFC parsed no elements"
    # every parsed element must survive element mapping (catch-all guarantees it)
    assert len(mapped) == len(objects), (
        f"EM dropped {len(objects) - len(mapped)} of {len(objects)} elements"
    )


def test_every_guid_reaches_city_gml(full_pipeline):
    context, city_gml = full_pipeline
    # every element's GUID must be present in the CityGML output (as a gml:id
    # on its feature or a GUID generic attribute), so nothing is silently lost.
    obj_guids = {o["GUID"] for o in context["objects"] if o.get("GUID")}
    missing = {g for g in obj_guids if g not in city_gml}
    assert not missing, f"{len(missing)} element GUID(s) missing from city.gml"


def test_output_is_renderable_citygml_with_geometry(full_pipeline):
    _, city_gml = full_pipeline
    # a viewer needs an extent and real coordinates to draw anything
    assert "<gml:Envelope" in city_gml
    assert "<gml:posList" in city_gml
    assert city_gml.count("<gml:posList") > 100  # thousands of triangles expected


def test_mapping_is_semantically_varied_not_building_only(full_pipeline):
    _, city_gml = full_pipeline
    types = _feature_types(city_gml)
    # a healthy full-element mapping yields several distinct CityGML features,
    # not a single building object.
    assert "WallSurface" in types
    assert len(types) >= 5, f"expected varied CityGML features, got {sorted(types)}"


def test_config_has_catch_all_em_rule():
    """The EM stage must end with a '.*' catch-all so unknown IFC types map too."""
    with open(CONFIG, encoding="utf-8") as f:
        pipeline = json.load(f)["BIM_GIS_mapping.pipeline"]
    em = next(s for s in pipeline if s.get("type") == "EM")
    sources = [r.get("source") for r in em["rule"]]
    assert ".*" in sources, "EM rules lack a '.*' catch-all; some elements could be dropped"
    # the catch-all must be last (rules are first-match-wins)
    assert sources[-1] == ".*", "the '.*' catch-all must be the last EM rule"
