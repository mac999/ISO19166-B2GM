"""LM operators run in local metres even when CM has already placed the model.

A CM stage placed before LM projects the geometry (EPSG:3857 inflates xy by
k ~ 1.26 at Seoul); operators like footprint/OBB/extrude must not work on
those inflated coordinates.  ``apply_placement`` keeps the local vertices and
``assign_lod`` runs the chain on them, projecting only the result - so a
CM-first pipeline ends up with the same geometry as a CM-last one.
"""

import copy

import pytest

import B2GM_CM as CM
import B2GM_LM as LM

pyproj = pytest.importorskip("pyproj")

RULES = [{
    "source": "IfcWall",
    "lod": "LOD1",
    "operation": [
        {"op": "footprint"},
        {"op": "extrude", "args": {"height": {"$extent": "z"}}},
    ],
}]


def wall():
    # a 10 x 0.3 x 3 m wall as two triangles per face is overkill; a thin
    # triangle is enough for footprint -> extrude
    return {"name": "W", "ifc_type": "IfcWall", "GUID": "w1",
            "_destination": "WallSurface",
            "geometry": {"verts": [0, 0, 0, 10, 0, 0, 10, 0.3, 0,
                                   0, 0, 3, 10, 0, 3, 10, 0.3, 3],
                         "faces": [0, 1, 2, 3, 4, 5]}}


def placement():
    return CM.Placement((127.0550383, 37.5061055, 30.0), "EPSG:3857")


def test_apply_placement_keeps_the_local_vertices():
    objs = [wall()]
    local = list(objs[0]["geometry"]["verts"])
    CM.apply_placement(objs, placement())
    assert objs[0]["geometry"]["local_verts"] == local
    assert objs[0]["geometry"]["verts"] != local


def test_cm_first_matches_lm_then_cm():
    rules = LM.rules_from_stage({"rule": copy.deepcopy(RULES)})
    place = placement()

    # reference: LM in local coordinates, then placed (the CM-last pipeline)
    reference = LM.assign_lod([wall()], rules)
    CM.apply_placement(reference, place)
    want = reference[0]["_lod_geometry"]["verts"]

    # CM first: geometry already projected when LM runs
    placed = [wall()]
    CM.apply_placement(placed, place)
    got_objs = LM.assign_lod(placed, rules, placement=place)
    got = got_objs[0]["_lod_geometry"]["verts"]

    assert len(got) == len(want)
    assert max(abs(a - b) for a, b in zip(got, want)) < 1e-6


def test_block_height_stays_metric_after_cm():
    place = placement()
    placed = [wall()]
    CM.apply_placement(placed, place)
    rules = LM.rules_from_stage({"rule": copy.deepcopy(RULES)})
    tagged = LM.assign_lod(placed, rules, placement=place)
    verts = tagged[0]["_lod_geometry"]["verts"]
    zs = verts[2::3]
    # $extent z was read from local metres: the block is exactly 3 m tall
    assert abs((max(zs) - min(zs)) - 3.0) < 1e-9


def test_assign_lod_without_placement_is_unchanged():
    rules = LM.rules_from_stage({"rule": copy.deepcopy(RULES)})
    tagged = LM.assign_lod([wall()], rules)
    verts = tagged[0]["_lod_geometry"]["verts"]
    assert min(verts[0::3]) == pytest.approx(0.0)
    assert max(verts[0::3]) == pytest.approx(10.0)
