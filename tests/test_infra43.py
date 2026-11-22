"""IFC 4.3 infrastructure: Bridge, Tunnel and Transportation destinations.

The writers accept the CityGML bridge / tunnel / transportation modules, and
the pipeline reads an IFC4X3 file whose facilities (IfcBridge, IfcRoad,
IfcRailway) carry their decks and pavements.
"""

import json
import os
import xml.etree.ElementTree as ET

import pytest

import B2GM_GIS as GIS


def _local(tag):
    return tag.split("}")[-1]


def _ns(tag):
    return tag.split("}")[0].strip("{") if "}" in tag else ""


def tri(z=0.0):
    return {"verts": [0, 0, z, 10, 0, z, 10, 5, z], "faces": [0, 1, 2]}


INFRA_OBJS = [
    {"name": "Deck", "ifc_type": "IfcSlab", "GUID": "d1",
     "_destination": "Bridge", "geometry": tri(10.0), "pset": {}},
    {"name": "Bore", "ifc_type": "IfcSlab", "GUID": "t1",
     "_destination": "Tunnel", "geometry": tri(-5.0), "pset": {}},
    {"name": "Pavement", "ifc_type": "IfcPavement", "GUID": "p1",
     "_destination": "Road", "geometry": tri(0.0), "pset": {}},
    {"name": "Track", "ifc_type": "IfcRail", "GUID": "r1",
     "_destination": "Railway", "geometry": tri(0.2), "pset": {}},
]


def test_citygml2_writes_infrastructure_members(tmp_path):
    out = tmp_path / "city.gml"
    n = GIS.GIS().store(str(out), INFRA_OBJS, {"rule": []})
    assert n == 5  # the building wrapper plus the four members
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    found = {_local(el.tag): _ns(el.tag) for el in root.iter()
             if _local(el.tag) in ("Bridge", "Tunnel", "Road", "Railway")}
    assert found["Bridge"].endswith("bridge/2.0")
    assert found["Tunnel"].endswith("tunnel/2.0")
    assert found["Road"].endswith("transportation/2.0")
    assert found["Railway"].endswith("transportation/2.0")


def test_citygml3_writes_infrastructure_members(tmp_path):
    out = tmp_path / "city.gml"
    n = GIS.GIS().store(str(out), INFRA_OBJS, {"rule": []}, version="3.0")
    assert n == 5  # the building wrapper plus the four members
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    found = {_local(el.tag): _ns(el.tag) for el in root.iter()
             if _local(el.tag) in ("Bridge", "Tunnel", "Road", "Railway")}
    assert found["Bridge"].endswith("bridge/3.0")
    assert found["Tunnel"].endswith("tunnel/3.0")
    assert found["Road"].endswith("transportation/3.0")
    assert found["Railway"].endswith("transportation/3.0")


def test_web_viewer_reads_infrastructure_features(tmp_path):
    import B2GM_web

    out = tmp_path / "city.gml"
    GIS.GIS().store(str(out), INFRA_OBJS, {"rule": []})
    features = B2GM_web.read_citygml(str(out))
    classes = {f["gis_class"] for f in features}
    assert {"Bridge", "Tunnel", "Road", "Railway"} <= classes


# --- an IFC4X3 file through the whole pipeline ------------------------------
@pytest.fixture(scope="module")
def ifc43_file(tmp_path_factory):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    try:
        f = ifcopenshell.file(schema="IFC4X3")
    except Exception:
        pytest.skip("ifcopenshell has no IFC4X3 schema")

    guid = ifcopenshell.guid.new

    def placement(z=0.0):
        return f.create_entity(
            "IfcLocalPlacement", RelativePlacement=f.create_entity(
                "IfcAxis2Placement3D", Location=f.create_entity(
                    "IfcCartesianPoint", Coordinates=(0.0, 0.0, float(z)))))

    def slab(name, ifc_class, dx, dy, dz, z):
        profile = f.create_entity(
            "IfcRectangleProfileDef", ProfileType="AREA",
            Position=f.create_entity("IfcAxis2Placement2D", Location=f.create_entity(
                "IfcCartesianPoint", Coordinates=(0.0, 0.0))),
            XDim=float(dx), YDim=float(dy))
        solid = f.create_entity(
            "IfcExtrudedAreaSolid", SweptArea=profile,
            Position=f.create_entity("IfcAxis2Placement3D", Location=f.create_entity(
                "IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))),
            ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(dz))
        shape = f.create_entity("IfcShapeRepresentation", ContextOfItems=context,
                                RepresentationIdentifier="Body",
                                RepresentationType="SweptSolid", Items=[solid])
        return f.create_entity(
            ifc_class, GlobalId=guid(), Name=name, ObjectPlacement=placement(z),
            Representation=f.create_entity("IfcProductDefinitionShape",
                                           Representations=[shape]))

    context = f.create_entity(
        "IfcGeometricRepresentationContext", ContextType="Model",
        CoordinateSpaceDimension=3, Precision=1e-5,
        WorldCoordinateSystem=f.create_entity("IfcAxis2Placement3D",
                                              Location=f.create_entity(
                                                  "IfcCartesianPoint",
                                                  Coordinates=(0.0, 0.0, 0.0))))
    project = f.create_entity(
        "IfcProject", GlobalId=guid(), Name="Infra",
        RepresentationContexts=[context],
        UnitsInContext=f.create_entity("IfcUnitAssignment", Units=[
            f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")]))
    site = f.create_entity("IfcSite", GlobalId=guid(), Name="Site",
                           ObjectPlacement=placement())
    bridge = f.create_entity("IfcBridge", GlobalId=guid(), Name="Han Bridge",
                             ObjectPlacement=placement())
    road = f.create_entity("IfcRoad", GlobalId=guid(), Name="Approach Road",
                           ObjectPlacement=placement())
    f.create_entity("IfcRelAggregates", GlobalId=guid(),
                    RelatingObject=project, RelatedObjects=[site])
    f.create_entity("IfcRelAggregates", GlobalId=guid(),
                    RelatingObject=site, RelatedObjects=[bridge, road])

    deck = slab("Deck", "IfcSlab", 30.0, 8.0, 0.6, 10.0)
    pavement = slab("Pavement", "IfcPavement", 40.0, 7.0, 0.3, 0.0)
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid(),
                    RelatingStructure=bridge, RelatedElements=[deck])
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid(),
                    RelatingStructure=road, RelatedElements=[pavement])

    path = tmp_path_factory.mktemp("ifc43") / "infra.ifc"
    f.write(str(path))
    return str(path)


def test_parser_reads_ifc43_products(ifc43_file):
    import B2GM_BIM

    objects = B2GM_BIM.BIM().parse(ifc43_file)
    types = {o["ifc_type"] for o in objects}
    assert {"IfcBridge", "IfcRoad", "IfcSlab", "IfcPavement"} <= types
    deck = next(o for o in objects if o["ifc_type"] == "IfcSlab")
    assert deck.get("geometry"), "the deck's extruded solid must tessellate"


def test_pipeline_maps_ifc43_to_citygml(ifc43_file, tmp_path):
    import B2GM_main

    pipeline = tmp_path / "pipe.json"
    pipeline.write_text(json.dumps({
        "BIM_GIS_mapping.pipeline": [
            {"type": "EM", "output": "city.gml", "rule": [
                {"source": "IfcBridge", "destination": "Bridge"},
                {"source": "IfcSlab", "destination": "Bridge"},
                {"source": "IfcRoad", "destination": "Road"},
                {"source": "IfcPavement", "destination": "Road"},
            ]},
        ]}), encoding="utf-8")
    context = B2GM_main.mapping_ifc_to_target(
        ifc43_file, "city.gml", str(pipeline), str(tmp_path))
    root = ET.parse(context["final_output"]).getroot()
    locals_ = [_local(el.tag) for el in root.iter()]
    assert "Bridge" in locals_ and "Road" in locals_
    # the deck geometry made it through
    text = open(context["final_output"], encoding="utf-8").read()
    assert "posList" in text
