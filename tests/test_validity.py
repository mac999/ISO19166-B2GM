"""Solid validity checks on meshes and on written CityGML files."""

import shutil

import pytest

import B2GM_validate as V

# a unit cube: 8 vertices, 12 outward-facing triangles
CUBE_VERTS = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0,
              0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1]
CUBE_FACES = [0, 2, 1, 0, 3, 2,      # bottom (z=0, facing down)
              4, 5, 6, 4, 6, 7,      # top (z=1, facing up)
              0, 1, 5, 0, 5, 4,      # front (y=0)
              1, 2, 6, 1, 6, 5,      # right (x=1)
              2, 3, 7, 2, 7, 6,      # back (y=1)
              3, 0, 4, 3, 4, 7]      # left (x=0)


def cube():
    return {"verts": list(CUBE_VERTS), "faces": list(CUBE_FACES)}


def test_closed_cube_is_valid():
    assert V.mesh_errors(cube()) == []
    assert V.solid_errors(cube()) == []


def test_open_mesh_is_reported():
    geom = cube()
    geom["faces"] = geom["faces"][6:]  # remove the bottom
    assert any("not closed" in e for e in V.solid_errors(geom))


def test_flipped_face_is_reported():
    geom = cube()
    geom["faces"][0:3] = [0, 1, 2]  # bottom triangle reversed
    assert any("orientation" in e for e in V.solid_errors(geom))


def test_inward_shell_is_reported():
    geom = cube()
    flipped = []
    for i in range(0, len(geom["faces"]), 3):
        a, b, c = geom["faces"][i:i + 3]
        flipped += [a, c, b]
    geom["faces"] = flipped
    assert any("inward" in e for e in V.solid_errors(geom))


def test_degenerate_triangle_is_reported():
    geom = {"verts": [0, 0, 0, 1, 0, 0, 2, 0, 0], "faces": [0, 1, 2]}
    assert any("degenerate" in e for e in V.mesh_errors(geom))


def test_extruded_prism_passes():
    from shapely.geometry import Polygon

    import B2GM_LM_operators as OP

    solid = OP.extrude(Polygon([(0, 0), (4, 0), (4, 2), (0, 2)]), height=3.0)
    geom = OP.to_brep(solid)
    assert V.solid_errors(geom) == []


def test_written_citygml_solids_validate(tmp_path):
    import B2GM_GIS as GIS

    out = tmp_path / "city.gml"
    objs = [{"name": "Room", "ifc_type": "IfcSpace", "GUID": "r1",
             "_destination": "Room", "_lod": "LOD2",
             "geometry": cube()}]
    GIS.GIS().store(str(out), objs, {"rule": []}, version="3.0")
    text = out.read_text(encoding="utf-8")
    assert "gml:Solid" in text  # the closed cube went out as a solid
    assert V.citygml_errors(str(out)) == []


@pytest.mark.skipif(shutil.which("val3dity") is None,
                    reason="val3dity binary not installed")
def test_val3dity_agrees(tmp_path):
    import B2GM_GIS as GIS

    out = tmp_path / "city.gml"
    objs = [{"name": "Room", "ifc_type": "IfcSpace", "GUID": "r1",
             "_destination": "Room", "_lod": "LOD2", "geometry": cube()}]
    GIS.GIS().store(str(out), objs, {"rule": []}, version="3.0")
    report = V.run_val3dity(str(out))
    assert report is not None
    assert report.get("validity") in (True, "true") or report.get("all_errors") == []
