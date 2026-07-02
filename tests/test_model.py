"""Tests for the B2GM conceptual data model."""

import B2GM_model as M


def test_property_type_inference():
    assert M.PropertyType.of(3) == M.PropertyType.INTEGER
    assert M.PropertyType.of(3.5) == M.PropertyType.REAL
    assert M.PropertyType.of("text") == M.PropertyType.STRING
    # bool must not be reported as integer
    assert M.PropertyType.of(True) == M.PropertyType.STRING


def test_property_to_dict_infers_type():
    p = M.property("Height", 3.0)
    d = p.to_dict()
    assert d == {"name": "Height", "value": 3.0, "type": "real"}


def test_property_set_add_and_get():
    ps = M.property_set("Pset_WallCommon", M.PropertySetType.GENERAL)
    ps.add_value("IsExternal", "T")
    ps.add_value("Height", 3.0)
    assert len(ps) == 2
    assert ps.get("Height").value == 3.0
    assert ps.get("missing") is None
    assert ps.type == "general"


def test_element_and_model_to_dict():
    m = M.model()
    e = m.add(M.element(name="IfcWall", guid="0001"))
    assert e.code == "IfcWall"
    ps = e.add_property_set(M.property_set("Pset_WallCommon"))
    ps.add_value("IsExternal", "T")
    e.lod = M.LOD("LOD1")

    d = m.to_dict()
    assert d["elements"][0]["name"] == "IfcWall"
    assert d["elements"][0]["pset"]["Pset_WallCommon"]["IsExternal"] == "T"
    assert d["elements"][0]["lod"]["name"] == "LOD1"


def test_model_used_as_base_carries_model_data():
    class Dummy(M.model):
        pass

    d = Dummy()
    assert d.model_data is None
    assert d.elements == []
    d.model_data = 123
    assert d.model_data == 123
