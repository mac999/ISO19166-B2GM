"""Generic attributes keep the value's type: int / double / date, not all strings."""

import datetime
import xml.etree.ElementTree as ET

import B2GM_GIS as GIS


def _local(tag):
    return tag.split("}")[-1]


def _attrs_by_kind(root):
    """{(kind, name): value} over every gen:*Attribute in a 2.0 document."""
    out = {}
    for el in root.iter():
        local = _local(el.tag)
        if local.endswith("Attribute") and el.get("name"):
            value = next((v.text for v in el if _local(v.tag) == "value"), None)
            out.setdefault((local, el.get("name")), value)
    return out


OBJS = [
    {"name": "Bld", "ifc_type": "IfcBuilding", "GUID": "b1",
     "_destination": "CityModel.Building",
     "pset": {"Common": {
         "NumberOfStoreys": 4,
         "Height": 12.5,
         "IsExternal": True,
         "IssueDate": "2024-05-01",
         "Status": "built",
     }}},
    {"name": "Wall", "ifc_type": "IfcWall", "GUID": "w1",
     "_destination": "WallSurface",
     "pset": {"Dim": {"Area": 7.25, "Count": 2,
                      "Checked": datetime.date(2025, 1, 31)}},
     "geometry": {"verts": [0, 0, 0, 1, 0, 0, 1, 0, 2], "faces": [0, 1, 2]}},
]


def test_attribute_kind_classification():
    assert GIS.attribute_kind(4) == "int"
    assert GIS.attribute_kind(12.5) == "double"
    assert GIS.attribute_kind(True) == "string"  # generics have no boolean
    assert GIS.attribute_kind("2024-05-01") == "date"
    assert GIS.attribute_kind(datetime.date(2025, 1, 31)) == "date"
    assert GIS.attribute_kind("built") == "string"
    assert GIS.attribute_kind("12.5") == "string"  # strings of digits stay strings
    assert GIS.attribute_kind(None) == "string"


def test_attribute_text_normalises_booleans_and_dates():
    assert GIS.attribute_text(True) == "true"
    assert GIS.attribute_text(False) == "false"
    assert GIS.attribute_text(datetime.datetime(2025, 1, 31, 10, 0)) == "2025-01-31"
    assert GIS.attribute_text(4) == "4"


def test_citygml2_attributes_are_typed(tmp_path):
    out = tmp_path / "city.gml"
    GIS.GIS().store(str(out), OBJS, {"rule": []})
    attrs = _attrs_by_kind(ET.fromstring(out.read_text(encoding="utf-8")))

    assert attrs[("intAttribute", "Common.NumberOfStoreys")] == "4"
    assert attrs[("doubleAttribute", "Common.Height")] == "12.5"
    assert attrs[("dateAttribute", "Common.IssueDate")] == "2024-05-01"
    assert attrs[("stringAttribute", "Common.Status")] == "built"
    assert attrs[("stringAttribute", "Common.IsExternal")] == "true"
    assert attrs[("doubleAttribute", "Dim.Area")] == "7.25"
    assert attrs[("intAttribute", "Dim.Count")] == "2"
    assert attrs[("dateAttribute", "Dim.Checked")] == "2025-01-31"
    # identification attributes stay strings
    assert attrs[("stringAttribute", "ifc_type")] == "IfcBuilding"


def test_citygml3_attributes_are_typed(tmp_path):
    out = tmp_path / "city.gml"
    GIS.GIS().store(str(out), OBJS, {"rule": []}, version="3.0")
    text = out.read_text(encoding="utf-8")
    root = ET.fromstring(text)

    found = {}
    for el in root.iter():
        local = _local(el.tag)
        if local in ("StringAttribute", "IntAttribute", "DoubleAttribute",
                     "DateAttribute"):
            name = next((c.text for c in el if _local(c.tag) == "name"), "")
            value = next((c.text for c in el if _local(c.tag) == "value"), "")
            found.setdefault((local, name), value)

    assert found[("IntAttribute", "Common.NumberOfStoreys")] == "4"
    assert found[("DoubleAttribute", "Common.Height")] == "12.5"
    assert found[("DateAttribute", "Common.IssueDate")] == "2024-05-01"
    assert found[("StringAttribute", "Common.Status")] == "built"
    assert found[("StringAttribute", "ifc_type")] == "IfcBuilding"


def test_web_reader_keeps_typed_attributes(tmp_path):
    import B2GM_web

    out = tmp_path / "city.gml"
    GIS.GIS().store(str(out), OBJS, {"rule": []})
    features = B2GM_web.read_citygml(str(out))
    wall = next(f for f in features if f["name"] == "Wall")
    assert wall["attributes"]["Dim.Area"] == "7.25"
    assert wall["attributes"]["Dim.Count"] == "2"


def test_inspect_groups_typed_attributes(tmp_path):
    import B2GM_inspect

    out = tmp_path / "city.gml"
    GIS.GIS().store(str(out), OBJS, {"rule": []})
    result = B2GM_inspect.inspect_path(str(out))
    names = []
    for node in result["tree"]:
        stack = [node]
        while stack:
            n = stack.pop()
            names.append(n.get("name"))
            stack.extend(n.get("children") or [])
    assert "Wall" in names
