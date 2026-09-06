"""CityGML 3.0 output: version switch, restructured features, storeys."""
import json
import os
import re
import xml.etree.ElementTree as ET

import pytest

import B2GM_citygml3 as C3
import B2GM_GIS

CORE = "{http://www.opengis.net/citygml/3.0}"
BLDG = "{http://www.opengis.net/citygml/building/3.0}"
CON = "{http://www.opengis.net/citygml/construction/3.0}"
GEN = "{http://www.opengis.net/citygml/generics/3.0}"
LUSE = "{http://www.opengis.net/citygml/landuse/3.0}"
GML = "{http://www.opengis.net/gml/3.2}"


def local(element):
    return re.sub(r"\{.*\}", "", element.tag)


def triangle(z=0.0):
    return {"verts": [0, 0, z, 1, 0, z, 1, 1, z], "faces": [0, 1, 2]}


def closed_box():
    """A tetrahedron: every edge shared by exactly two faces."""
    return {"verts": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1],
            "faces": [0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3]}


@pytest.fixture
def objects():
    return [
        {"name": "House", "GUID": "b1", "_destination": "CityModel.Building",
         "_lod": "LOD1", "geometry": closed_box(), "pset": {"P": {"a": "1"}}},
        {"name": "Wall", "GUID": "w1", "_destination": "WallSurface", "_lod": "LOD2",
         "geometry": triangle(), "pset": {},
         "relationship": [{"name": "voids", "related": {"guid": "op1"}}]},
        {"name": "Window", "GUID": "win1", "_destination": "Window", "_lod": "LOD3",
         "geometry": triangle(1.0), "pset": {},
         "relationship": [{"name": "fills", "related": {"guid": "op1"}}]},
        {"name": "Roof", "GUID": "rf1", "_destination": "RoofSurface", "_lod": "LOD2",
         "geometry": triangle(5.0), "pset": {}},
        {"name": "Kitchen", "GUID": "r1", "_destination": "Room", "_lod": "LOD1",
         "geometry": closed_box(), "pset": {}},
        {"name": "Level 1", "GUID": "st1", "_destination": "BuildingStorey", "pset": {}},
        {"name": "Site", "GUID": "s1", "_destination": "LandUse", "_lod": "LOD0",
         "pset": {}},
    ]


@pytest.fixture
def model(tmp_path, objects):
    path = str(tmp_path / "city3.gml")
    B2GM_GIS.GIS().store(path, objects, {"rule": []}, version="3.0")
    return ET.parse(path).getroot()


# --- version selection ------------------------------------------------------
def test_normalise_version_accepts_common_spellings():
    assert B2GM_GIS.normalise_version("3") == "3.0"
    assert B2GM_GIS.normalise_version("CityGML 3.0") == "3.0"
    assert B2GM_GIS.normalise_version(None) == "2.0"
    with pytest.raises(ValueError):
        B2GM_GIS.normalise_version("1.0")


def test_version_from_stage_prefers_the_stage():
    assert B2GM_GIS.version_from_stage({"citygml_version": "3.0"}) == "3.0"
    assert B2GM_GIS.version_from_stage({}, "3.0") == "3.0"
    assert B2GM_GIS.version_from_stage(None) == "2.0"


def test_store_defaults_to_20(tmp_path, objects):
    path = str(tmp_path / "c.gml")
    B2GM_GIS.GIS().store(path, objects, {"rule": []})
    assert "citygml/2.0" in open(path, encoding="utf-8").read(600)


def test_store_30_uses_the_30_namespaces(model):
    assert model.tag == f"{CORE}CityModel"


# --- restructured features --------------------------------------------------
def test_storey_becomes_a_real_feature(model):
    """The 2.0 limitation: CityGML 3.0 has bldg:Storey, so it is no longer lost."""
    subdivision = model.find(f".//{BLDG}buildingSubdivision")
    assert subdivision is not None
    storey = subdivision.find(f"{BLDG}Storey")
    assert storey is not None
    assert storey.find(f"{GML}name").text == "Level 1"


def test_thematic_surfaces_move_to_core_boundary_and_construction(model):
    boundary = model.find(f".//{CORE}boundary")
    assert boundary is not None
    assert boundary.find(f"{CON}WallSurface") is not None


def test_openings_become_filling_surfaces(model):
    """3.0 splits Window into a space and a WindowSurface; a wall opening is
    the surface, and con:fillingSurface accepts only the surface."""
    wall = model.find(f".//{CON}WallSurface")
    filling = wall.find(f"{CON}fillingSurface")
    assert filling is not None
    assert filling.find(f"{CON}WindowSurface") is not None
    assert filling.find(f"{CON}Window") is None


def test_hosting_surface_moves_to_lod3(model):
    """con:fillingSurface needs LOD3, so the wall that hosts it follows."""
    wall = model.find(f".//{CON}WallSurface")
    assert wall.find(f"{CORE}lod3MultiSurface") is not None


def test_room_becomes_building_room(model):
    room_property = model.find(f".//{BLDG}buildingRoom")
    assert room_property is not None
    assert room_property.find(f"{BLDG}BuildingRoom") is not None


def test_landuse_is_its_own_member(model):
    members = model.findall(f"{CORE}cityObjectMember")
    assert len(members) == 2
    assert members[1].find(f"{LUSE}LandUse") is not None


# --- geometry ---------------------------------------------------------------
def test_closed_mesh_is_written_as_a_solid(model):
    building = model.find(f".//{BLDG}Building")
    solid_property = building.find(f"{CORE}lod1Solid")
    assert solid_property is not None
    solid = solid_property.find(f"{GML}Solid")
    assert solid.find(f"{GML}exterior/{GML}Shell") is not None


def test_open_mesh_stays_a_multisurface(model):
    roof = model.find(f".//{CON}RoofSurface")
    assert roof.find(f"{CORE}lod2MultiSurface/{GML}MultiSurface") is not None
    assert roof.find(f"{CORE}lod2Solid") is None


def test_is_closed_shell():
    assert C3.is_closed_shell(closed_box())
    assert not C3.is_closed_shell(triangle())
    assert not C3.is_closed_shell({"verts": [], "faces": []})


def test_lod_level_clamps_lod4():
    assert C3.lod_level("LOD2") == 2
    assert C3.lod_level("LOD4") == 3          # 3.0 has no LOD4
    assert C3.lod_level("nonsense") == 2


def test_space_with_open_mesh_skips_the_missing_lod1_multisurface():
    """AbstractSpace has no lod1MultiSurface, so LOD1 open meshes move to LOD2."""
    name, as_solid = C3.geometry_property("room", "LOD1", triangle())
    assert name == "core:lod2MultiSurface" and as_solid is False


def test_generic_attributes_use_element_name_and_value(model):
    building = model.find(f".//{BLDG}Building")
    attribute = building.find(f"{CORE}genericAttribute/{GEN}StringAttribute")
    assert attribute is not None
    assert attribute.find(f"{GEN}name").text
    assert attribute.find(f"{GEN}value") is not None


def test_gml_ids_are_unique(model):
    ids = [e.get(f"{GML}id") for e in model.iter()]
    ids = [i for i in ids if i]
    assert len(ids) == len(set(ids))


def test_building_children_follow_the_30_sequence(model):
    """AbstractBuildingType 3.0: boundary, geometry, installation, room, subdivision."""
    building = model.find(f".//{BLDG}Building")
    tracked = ("boundary", "lod1Solid", "lod2Solid", "lod2MultiSurface",
               "buildingInstallation", "buildingRoom", "buildingSubdivision")
    expected = list(tracked)
    order = [local(c) for c in building if local(c) in tracked]
    positions = [expected.index(name) for name in order]
    assert positions == sorted(positions), order


# --- pipeline integration ---------------------------------------------------
def test_pipeline_file_can_pin_the_version(tmp_path):
    import B2GM_main

    ifc = os.path.join(os.path.dirname(__file__), "..", "input_data",
                       "duplex_apartment.ifc")
    if not os.path.exists(ifc):
        pytest.skip("sample IFC not available")

    pipeline = tmp_path / "pipe.json"
    pipeline.write_text(json.dumps({
        "citygml_version": "3.0",
        "BIM_GIS_mapping.pipeline": [
            {"type": "EM", "output": "city.gml",
             "rule": [{"source": "IfcBuildingStorey", "destination": "BuildingStorey"},
                      {"source": ".*", "destination": "GenericCityObject"}]},
        ]}), encoding="utf-8")

    context = B2GM_main.mapping_ifc_to_target(ifc, "city.gml", str(pipeline), str(tmp_path))
    assert context["citygml_version"] == "3.0"
    root = ET.parse(context["final_output"]).getroot()
    assert root.tag == f"{CORE}CityModel"
    assert len(root.findall(f".//{BLDG}Storey")) == 4


# --- storey hierarchy -------------------------------------------------------
@pytest.fixture
def storeyed(tmp_path):
    """A building whose storey contains a room, a wall and an installation."""
    objects = [
        {"name": "House", "GUID": "b1", "_destination": "CityModel.Building", "pset": {}},
        {"name": "Level 1", "GUID": "st1", "_destination": "BuildingStorey", "pset": {},
         "relationship": [
             {"name": "contains", "related": {"guid": "w1"}},
             {"name": "contains", "related": {"guid": "r1"}},
             {"name": "contains", "related": {"guid": "i1"}}]},
        {"name": "Wall", "GUID": "w1", "_destination": "WallSurface", "_lod": "LOD2",
         "geometry": triangle(), "pset": {}},
        {"name": "Kitchen", "GUID": "r1", "_destination": "Room", "_lod": "LOD2",
         "geometry": triangle(1.0), "pset": {}},
        {"name": "Beam", "GUID": "i1", "_destination": "BuildingInstallation",
         "_lod": "LOD2", "geometry": triangle(2.0), "pset": {}},
        {"name": "Loose wall", "GUID": "w2", "_destination": "WallSurface",
         "_lod": "LOD2", "geometry": triangle(3.0), "pset": {}},
    ]
    def build(nest):
        path = str(tmp_path / f"s{nest}.gml")
        B2GM_GIS.GIS().store(path, objects, {"rule": [], "nest_by_storey": nest},
                             version="3.0")
        return ET.parse(path).getroot()
    return build


def test_storey_holds_the_elements_it_contains(storeyed):
    root = storeyed(True)
    storey = root.find(f".//{BLDG}Storey")
    assert storey.find(f"{CORE}boundary/{CON}WallSurface") is not None
    assert storey.find(f"{BLDG}buildingRoom/{BLDG}BuildingRoom") is not None
    assert storey.find(f"{BLDG}buildingInstallation/{BLDG}BuildingInstallation") is not None


def test_uncontained_elements_stay_on_the_building(storeyed):
    root = storeyed(True)
    building = root.find(f".//{BLDG}Building")
    direct = [w for w in building.findall(f"{CORE}boundary/{CON}WallSurface")]
    assert len(direct) == 1
    assert direct[0].find(f"{GML}name").text == "Loose wall"


def test_nesting_can_be_switched_off(storeyed):
    root = storeyed(False)
    storey = root.find(f".//{BLDG}Storey")
    assert storey.find(f"{BLDG}buildingRoom") is None
    building = root.find(f".//{BLDG}Building")
    assert len(building.findall(f"{CORE}boundary/{CON}WallSurface")) == 2
    assert building.find(f"{BLDG}buildingRoom/{BLDG}BuildingRoom") is not None


def test_storey_children_follow_the_schema_sequence(storeyed):
    """StoreyType orders core:boundary before buildingInstallation/buildingRoom."""
    storey = storeyed(True).find(f".//{BLDG}Storey")
    tracked = ("boundary", "buildingConstructiveElement", "buildingInstallation",
               "buildingRoom")
    order = [local(c) for c in storey if local(c) in tracked]
    positions = [tracked.index(name) for name in order]
    assert positions == sorted(positions), order


def test_storey_contents_reads_both_relationship_kinds():
    resolved = [
        ({"GUID": "s1", "relationship": [
            {"name": "contains", "related": {"guid": "a"}},
            {"name": "aggregates", "related": {"guid": "b"}},
            {"name": "material", "related": {"guid": "c"}}]}, "BuildingStorey"),
    ]
    assert C3.storey_contents(resolved) == {"a": "s1", "b": "s1"}
