"""Tests for the GIS-side CityGML serialisation."""

import xml.etree.ElementTree as ET

import B2GM_GIS as GIS


def test_sanitize_tag():
    assert GIS.sanitize_tag("Project Issue Date") == "Project_Issue_Date"
    assert GIS.sanitize_tag("9_Volume") == "p_9_Volume"
    assert GIS.sanitize_tag("") == "prop"
    assert GIS.sanitize_tag("Height") == "Height"


def _read(path):
    return path.read_text(encoding="utf-8")


def _local(tag):
    """Strip the inherited default-namespace prefix from an ElementTree tag."""
    return tag.split("}")[-1]


def _local_tags(root):
    return [_local(el.tag) for el in root.iter()]


def test_store_writes_valid_citygml(tmp_path, bim_objects):
    out = tmp_path / "city.gml"
    stage = {"rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"}]}
    n = GIS.GIS().store(str(out), bim_objects, stage)

    assert n == 1  # only the building matches
    # must be well-formed XML
    root = ET.fromstring(_read(out))
    tags = _local_tags(root)
    assert "CityModel.Building" in tags
    assert "propertySet" in tags


def test_store_emits_lod_and_uses_destination(tmp_path, bim_objects):
    # simulate objects already mapped by EM + LM
    objs = [dict(bim_objects[0], _destination="CityModel.Building", _lod="LOD1")]
    out = tmp_path / "lod.gml"
    # empty rules: destination must come from the _destination tag
    GIS.GIS().store(str(out), objs, {"rule": []})

    root = ET.fromstring(_read(out))
    lod_values = [el.text for el in root.iter() if _local(el.tag) == "lod"]
    assert lod_values == ["LOD1"]
    assert any(_local(el.tag) == "CityModel.Building" for el in root.iter())


def test_store_escapes_special_characters(tmp_path):
    objs = [{"name": "A & B <test>", "ifc_type": "IfcBuilding", "pset": {}}]
    out = tmp_path / "esc.gml"
    GIS.GIS().store(str(out), objs, {"rule": [{"source": "IfcBuilding", "destination": "B"}]})
    root = ET.fromstring(_read(out))  # would raise if escaping were wrong
    names = [el.text for el in root.iter() if _local(el.tag) == "name"]
    assert names == ["A & B <test>"]
