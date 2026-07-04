"""Tests for the GIS-side CityGML 2.0 serialisation (geometry + attributes)."""

import xml.etree.ElementTree as ET

import B2GM_GIS as GIS


def test_sanitize_tag():
    assert GIS.sanitize_tag("Project Issue Date") == "Project_Issue_Date"
    assert GIS.sanitize_tag("9_Volume") == "p_9_Volume"
    assert GIS.sanitize_tag("") == "prop"
    assert GIS.sanitize_tag("Height") == "Height"


def test_gml_id_is_valid_ncname():
    # IFC GUIDs may contain '$' and start with a digit; gml:id must not.
    assert GIS.gml_id("1xS3BCk291UvhgP2$6eflK").replace("_", "").isalnum()
    assert not GIS.gml_id("9abc")[0].isdigit()


def _read(path):
    return path.read_text(encoding="utf-8")


def _local(tag):
    return tag.split("}")[-1]


def _generic_attrs(root):
    """Return {name: value} for every gen:stringAttribute in the document."""
    out = {}
    for sa in root.iter():
        if _local(sa.tag) == "stringAttribute":
            vals = [v.text for v in sa if _local(v.tag) == "value"]
            out.setdefault(sa.get("name"), []).append(vals[0] if vals else None)
    return out


def test_store_writes_valid_citygml2_with_envelope(tmp_path, bim_objects):
    out = tmp_path / "city.gml"
    stage = {"rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"}]}
    n = GIS.GIS().store(str(out), bim_objects, stage)

    assert n == 1  # only the building matches the rule
    root = ET.fromstring(_read(out))  # must be well-formed XML
    tags = [_local(el.tag) for el in root.iter()]
    assert _local(root.tag) == "CityModel"
    assert "Building" in tags
    assert "Envelope" in tags
    # building property-set values are preserved as generic attributes
    attrs = _generic_attrs(root)
    assert "Pset_BuildingCommon.NumberOfStoreys" in attrs


def test_store_emits_geometry_for_surfaces(tmp_path):
    objs = [
        {"name": "Bld", "ifc_type": "IfcBuilding", "GUID": "b1",
         "_destination": "CityModel.Building", "pset": {}},
        {"name": "Wall", "ifc_type": "IfcWallStandardCase", "GUID": "w1",
         "_destination": "WallSurface",
         "geometry": {"verts": [0, 0, 0, 1, 0, 0, 1, 0, 2], "faces": [0, 1, 2]}},
    ]
    out = tmp_path / "geo.gml"
    GIS.GIS().store(str(out), objs, {"rule": []})
    root = ET.fromstring(_read(out))
    tags = [_local(el.tag) for el in root.iter()]
    assert "WallSurface" in tags
    assert "lod2MultiSurface" in tags
    pos = [el.text for el in root.iter() if _local(el.tag) == "posList"]
    assert pos and "0.0000" in pos[0]  # real coordinates emitted


def test_store_records_lod_and_destination(tmp_path, bim_objects):
    objs = [dict(bim_objects[0], _destination="CityModel.Building", _lod="LOD1")]
    out = tmp_path / "lod.gml"
    GIS.GIS().store(str(out), objs, {"rule": []})
    root = ET.fromstring(_read(out))
    assert any(_local(el.tag) == "Building" for el in root.iter())
    attrs = _generic_attrs(root)
    assert attrs.get("lod") == ["LOD1"]


def test_store_escapes_special_characters(tmp_path):
    objs = [{"name": "A & B <test>", "ifc_type": "IfcBuilding", "GUID": "b1", "pset": {}}]
    out = tmp_path / "esc.gml"
    GIS.GIS().store(str(out), objs, {"rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"}]})
    root = ET.fromstring(_read(out))  # would raise if escaping were wrong
    names = [el.text for el in root.iter() if _local(el.tag) == "name"]
    assert "A & B <test>" in names
