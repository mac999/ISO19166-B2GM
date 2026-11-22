"""The envelope operator: a watertight outer shell with semantic surfaces."""

import numpy as np
import pytest
from shapely.geometry import Polygon

import B2GM_LM as LM
import B2GM_LM_operators as OP
import B2GM_validate as V

pytest.importorskip("manifold3d")


def box(x0, y0, z0, dx, dy, dz):
    return OP.extrude(Polygon([(x0, y0), (x0 + dx, y0), (x0 + dx, y0 + dy),
                               (x0, y0 + dy)]), height=dz, base_z=z0)


def brep_of(solid):
    return OP.to_brep(solid)


def test_envelope_unions_overlapping_boxes():
    # two boxes overlapping by half: the union volume is 10*4*3 + 10*4*3 - 5*4*3
    merged = OP._merge_solids([box(0, 0, 0, 10, 4, 3), box(5, 0, 0, 10, 4, 3)])
    shell = OP.envelope(merged)
    assert isinstance(shell, OP.Solid)
    assert abs(shell.volume() - (120 + 120 - 60)) < 1e-6
    assert V.solid_errors(brep_of(shell)) == []


def test_envelope_drops_interior_cavities():
    # a room inside a building: the inner shell is not part of the envelope
    outer = box(0, 0, 0, 10, 10, 10)
    inner = box(3, 3, 3, 2, 2, 2)
    merged = OP._merge_solids([outer, inner])
    shell = OP.envelope(merged)
    assert abs(shell.volume() - 1000) < 1e-6


def test_envelope_falls_back_on_open_meshes():
    # a single triangle cannot union; the merged mesh must still come back
    open_mesh = OP.Solid(np.array([[0.0, 0, 0], [1, 0, 0], [1, 1, 0]]), [[0, 1, 2]])
    shell = OP.envelope(open_mesh)
    assert len(shell.faces) >= 1


def test_classify_faces_splits_a_cube():
    cube = box(0, 0, 0, 4, 4, 3)
    parts = OP.classify_faces(cube)
    assert set(parts) == {"RoofSurface", "WallSurface", "GroundSurface"}
    # the roof is the top 4x4 face, the ground the bottom one
    roof = parts["RoofSurface"]
    assert all(abs(v[2] - 3.0) < 1e-9 for v in roof.vertices)
    ground = parts["GroundSurface"]
    assert all(abs(v[2]) < 1e-9 for v in ground.vertices)
    walls = parts["WallSurface"]
    assert len(walls.faces) >= 4


def wall_obj(guid, x0):
    geom = brep_of(box(x0, 0, 0, 6, 0.3, 3))
    return {"name": f"W{guid}", "ifc_type": "IfcWall", "GUID": guid,
            "_destination": "WallSurface", "geometry": geom}


BUILDING = {"name": "Bld", "ifc_type": "IfcBuilding", "GUID": "b1",
            "_destination": "CityModel.Building", "pset": {}}


def test_assign_lod_emits_semantic_envelope_surfaces():
    objects = [dict(BUILDING), wall_obj("w1", 0), wall_obj("w2", 3)]
    rules = LM.rules_from_stage({"rule": [{
        "source": "IfcBuilding", "lod": "LOD2",
        "aggregate": "IfcWall.*",
        "operation": [{"op": "envelope"}],
        "semantic_surfaces": True,
        "consume": "IfcWall.*",
    }]})
    tagged = LM.assign_lod(objects, rules)

    classes = [o.get("_destination") for o in tagged]
    assert "WallSurface" in classes and "RoofSurface" in classes
    assert "GroundSurface" in classes
    # the source walls were consumed; only derived surfaces remain as walls
    assert not any(o.get("ifc_type") == "IfcWall" for o in tagged)
    building = next(o for o in tagged if o.get("ifc_type") == "IfcBuilding")
    assert building.get("_lod_geometry")  # the envelope solid itself
    assert V.solid_errors(building["_lod_geometry"]) == []
    derived = [o for o in tagged if o.get("_derived_from") == "b1"]
    assert all(o.get("_lod") == "LOD2" for o in derived)


def test_consume_without_semantics_keeps_behaviour():
    objects = [dict(BUILDING), wall_obj("w1", 0)]
    rules = LM.rules_from_stage({"rule": [
        {"source": "IfcBuilding", "lod": "LOD1", "aggregate": "IfcWall.*",
         "operation": [{"op": "footprint"}, {"op": "extrude", "args": {"height": 3}}]},
        {"source": ".*", "lod": "LOD2"},
    ]})
    tagged = LM.assign_lod(objects, rules)
    assert len(tagged) == 2  # nothing consumed, nothing derived
