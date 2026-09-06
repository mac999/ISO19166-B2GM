"""CityGML 2.0 document structure: feature nesting, LoD and element order."""
import re
import xml.etree.ElementTree as ET

import pytest

import B2GM_GIS

CORE = "{http://www.opengis.net/citygml/2.0}"
BLDG = "{http://www.opengis.net/citygml/building/2.0}"
LUSE = "{http://www.opengis.net/citygml/landuse/2.0}"


def local(element):
    return re.sub(r"\{.*\}", "", element.tag)


def brep(z=0.0):
    return {"verts": [0, 0, z, 1, 0, z, 1, 1, z], "faces": [0, 1, 2]}


@pytest.fixture
def model(tmp_path):
    """A wall hosting a window, an installation, a room, a site and a storey."""
    objects = [
        {"name": "House", "GUID": "b1", "_destination": "CityModel.Building",
         "_lod": "LOD1", "geometry": brep(), "pset": {}},
        {"name": "Wall", "GUID": "w1", "_destination": "WallSurface",
         "geometry": brep(), "pset": {},
         "relationship": [{"name": "voids", "type": "association",
                           "related": {"guid": "op1", "type": "IfcOpeningElement"}}]},
        {"name": "Window", "GUID": "win1", "_destination": "Window",
         "geometry": brep(1.0), "pset": {},
         "relationship": [{"name": "fills", "type": "association",
                           "related": {"guid": "op1", "type": "IfcOpeningElement"}}]},
        {"name": "Orphan door", "GUID": "d1", "_destination": "Door",
         "geometry": brep(2.0), "pset": {}},
        {"name": "Beam", "GUID": "i1", "_destination": "BuildingInstallation",
         "geometry": brep(3.0), "pset": {}},
        {"name": "Kitchen", "GUID": "r1", "_destination": "Room",
         "geometry": brep(4.0), "pset": {}},
        {"name": "Site", "GUID": "s1", "_destination": "LandUse", "pset": {}},
        {"name": "Level 1", "GUID": "st1", "_destination": "BuildingStorey", "pset": {}},
    ]
    path = str(tmp_path / "city.gml")
    B2GM_GIS.GIS().store(path, objects, {"rule": []})
    return ET.parse(path).getroot()


def test_window_is_nested_as_an_opening_of_its_host_wall(model):
    wall = model.find(f".//{BLDG}WallSurface")
    assert wall is not None
    opening = wall.find(f"{BLDG}opening")
    assert opening is not None
    assert opening.find(f"{BLDG}Window") is not None


def test_hosting_surface_moves_to_lod3(model):
    """bldg:opening is only allowed from LOD3, so the host surface follows."""
    wall = model.find(f".//{BLDG}WallSurface")
    assert wall.find(f"{BLDG}lod3MultiSurface") is not None
    assert wall.find(f"{BLDG}lod2MultiSurface") is None


def test_opening_without_a_host_is_kept_as_an_installation(model):
    names = [n.text for n in model.iter(f"{BLDG}BuildingInstallation")]
    installations = model.findall(f".//{BLDG}BuildingInstallation")
    assert len(installations) == 2                       # beam + orphan door
    assert any(i.find("{http://www.opengis.net/gml}name").text == "Orphan door"
               for i in installations)


def test_room_is_an_interior_room_at_lod4(model):
    building = model.find(f".//{BLDG}Building")
    room_property = building.find(f"{BLDG}interiorRoom")
    assert room_property is not None
    room = room_property.find(f"{BLDG}Room")
    assert room.find(f"{BLDG}lod4MultiSurface") is not None


def test_landuse_is_its_own_city_object_member(model):
    members = model.findall(f"{CORE}cityObjectMember")
    assert len(members) == 2
    assert members[1].find(f"{LUSE}LandUse") is not None


def test_building_carries_its_lod1_block(model):
    building = model.find(f".//{BLDG}Building")
    assert building.find(f"{BLDG}lod1MultiSurface") is not None


def test_storey_has_no_citygml_2_feature_so_it_stays_an_attribute(model):
    """CityGML 2.0 has no Storey; the element survives as a generic attribute."""
    building = model.find(f".//{BLDG}Building")
    values = [a.get("name") for a in building.iter(
        "{http://www.opengis.net/citygml/generics/2.0}stringAttribute")]
    assert "gis_class" in values


def test_building_children_follow_the_schema_sequence(model):
    """AbstractBuildingType orders: geometry, outerBuildingInstallation,
    boundedBy, interiorRoom, consistsOfBuildingPart."""
    building = model.find(f".//{BLDG}Building")
    order = [local(child) for child in building
             if local(child) in ("lod1MultiSurface", "lod2MultiSurface",
                                 "outerBuildingInstallation", "boundedBy",
                                 "interiorRoom", "consistsOfBuildingPart")]
    expected = ["lod1MultiSurface", "outerBuildingInstallation", "boundedBy",
                "interiorRoom"]
    ranking = {name: i for i, name in enumerate(expected)}
    positions = [ranking[name] for name in order]
    assert positions == sorted(positions), order


def test_boundary_surface_puts_geometry_before_openings(model):
    """AbstractBoundarySurfaceType orders lod*MultiSurface before opening."""
    wall = model.find(f".//{BLDG}WallSurface")
    children = [local(c) for c in wall]
    assert children.index("lod3MultiSurface") < children.index("opening")


def test_gml_ids_are_unique(model):
    ids = [e.get("{http://www.opengis.net/gml}id") for e in model.iter()]
    ids = [i for i in ids if i]
    assert len(ids) == len(set(ids))


def test_schema_location_is_declared(tmp_path):
    path = str(tmp_path / "c.gml")
    B2GM_GIS.GIS().store(path, [], {"rule": []})
    text = open(path, encoding="utf-8").read()
    assert "schemaLocation" in text
    assert "citygml/2.0/cityGMLBase.xsd" in text
