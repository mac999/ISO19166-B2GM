import json
import os

import B2GM_inspect as INSPECT

HERE = os.path.dirname(os.path.abspath(__file__))
IFC4 = os.path.join(HERE, "simple_ifc4.ifc")

GML = """<?xml version="1.0" encoding="UTF-8"?>
<core:CityModel xmlns:core="http://www.opengis.net/citygml/2.0"
    xmlns:bldg="http://www.opengis.net/citygml/building/2.0"
    xmlns:gen="http://www.opengis.net/citygml/generics/2.0"
    xmlns:gml="http://www.opengis.net/gml">
  <gml:boundedBy><gml:Envelope srsName="EPSG:5186"/></gml:boundedBy>
  <core:cityObjectMember>
    <bldg:Building gml:id="b1">
      <gml:name>House</gml:name>
      <gen:stringAttribute name="Pset_BuildingCommon.NumberOfStoreys"><gen:value>2</gen:value></gen:stringAttribute>
      <bldg:boundedBy><bldg:WallSurface gml:id="w1">
        <gml:name>Wall</gml:name>
        <bldg:lod2MultiSurface><gml:MultiSurface><gml:surfaceMember><gml:Polygon gml:id="p1">
          <gml:exterior><gml:LinearRing><gml:posList>0 0 0 1 0 0 1 0 1 0 0 0</gml:posList></gml:LinearRing></gml:exterior>
        </gml:Polygon></gml:surfaceMember></gml:MultiSurface></bldg:lod2MultiSurface>
        <bldg:opening><bldg:Window gml:id="win1"><gml:name>Window</gml:name></bldg:Window></bldg:opening>
      </bldg:WallSurface></bldg:boundedBy>
    </bldg:Building>
  </core:cityObjectMember>
</core:CityModel>
"""


def test_citygml_tree_nests_surfaces_and_openings(tmp_path):
    path = tmp_path / "city.gml"
    path.write_text(GML, encoding="utf-8")
    result = INSPECT.inspect_path(str(path))
    assert result["kind"] == "citygml"
    building = result["tree"][0]
    assert (building["cls"], building["name"], building["id"]) == ("Building", "House", "b1")
    wall = building["children"][0]
    assert wall["cls"] == "WallSurface"
    # geometry ids (the polygon) are not features
    assert [c["id"] for c in wall["children"]] == ["win1"]
    groups = dict((title, items) for title, items in building["props"])
    assert ["NumberOfStoreys", "2"] in groups["Pset_BuildingCommon"]
    assert dict(dict(wall["props"])["Geometry"])["lod2MultiSurface"] == "1 polygons"
    assert ["CRS", "EPSG:5186"] in result["summary"]


def test_ifc_tree_follows_the_spatial_structure():
    result = INSPECT.inspect_path(IFC4)
    assert result["kind"] == "ifc"
    project = result["tree"][0]
    assert project["cls"] == "IfcProject"
    classes = set()

    def walk(node):
        classes.add(node["cls"])
        for child in node["children"]:
            walk(child)
    walk(project)
    assert {"IfcSite", "IfcBuilding", "IfcBuildingStorey"} <= classes
    storey = project
    while storey["cls"] != "IfcBuildingStorey":
        storey = storey["children"][0]
    element = storey["children"][0]
    groups = dict((title, items) for title, items in INSPECT.node_properties(IFC4, element["step"]))
    assert ["GlobalId", element["id"]] in groups["IFC " + element["cls"]]


def test_folder_metadata_reads_the_run_record(tmp_path):
    (tmp_path / "city.gml").write_text(GML, encoding="utf-8")
    (tmp_path / "b2gm_run.json").write_text(json.dumps(
        {"input": "a.ifc", "stages": [{"type": "LM", "output": "city.gml"}],
         "final_output": "city.gml"}), encoding="utf-8")
    groups = dict((title, items) for title, items in INSPECT.inspect_path(str(tmp_path))["meta"])
    assert ["files", 2] in groups["Folder"]
    assert ["final_output", "city.gml"] in groups["Pipeline run"]
    assert groups["Stages"] == [["LM", "city.gml"]]


def test_other_files_get_metadata(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("a\nb\n", encoding="utf-8")
    result = INSPECT.inspect_path(str(path))
    assert result["kind"] == "file"
    assert ["lines", 2] in result["meta"][0][1]
