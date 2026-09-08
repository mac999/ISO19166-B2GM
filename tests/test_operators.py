"""Tests for the general B2G LM operator library (ISO 19166 Table 8)."""

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon

import B2GM_LM_operators as OP


@pytest.fixture
def square():
    # 10 (x) by 20 (y) rectangle
    return Polygon([(0, 0), (10, 0), (10, 20), (0, 20)])


@pytest.fixture
def block(square):
    # extrude 12 (z) -> a 10 x 20 x 12 box
    return OP.extrude(square, OP.Vector3D((0, 0, 1)), height=12.0)


# --- extrude ---------------------------------------------------------------
def test_extrude_volume_and_vertex_count(block):
    assert block.volume() == pytest.approx(2400.0)  # 10*20*12
    assert len(block.vertices) == 8                  # box has 8 corners
    assert len(block.faces) == 6                     # top + bottom + 4 sides


def test_extrude_rejects_degenerate_inputs(square):
    with pytest.raises(ValueError):
        OP.extrude(Polygon(), (0, 0, 1), 5)
    with pytest.raises(ValueError):
        OP.extrude(square, (0, 0, 0), 5)  # zero direction


def test_extrude_multipolygon_sums_volume():
    a = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    b = Polygon([(10, 10), (13, 10), (13, 10 + 3), (10, 13)])
    mp = MultiPolygon([a, b])
    solid = OP.extrude(mp, (0, 0, 1), 5.0)
    assert solid.volume() == pytest.approx((4 + 9) * 5.0)


def test_extrude_base_z_offset(square):
    solid = OP.extrude(square, (0, 0, 1), 4.0, base_z=100.0)
    zmin, zmax = solid.vertices[:, 2].min(), solid.vertices[:, 2].max()
    assert (zmin, zmax) == pytest.approx((100.0, 104.0))


# --- footprint / projection / boundary -------------------------------------
def test_footprint_area(block):
    assert OP.footprint(block).area == pytest.approx(200.0)  # 10*20


def test_projection_planes(block):
    assert OP.projection(block, "XY").area == pytest.approx(200.0)  # 10*20
    assert OP.projection(block, "XZ").area == pytest.approx(120.0)  # 10*12
    assert OP.projection(block, "YZ").area == pytest.approx(240.0)  # 20*12


def test_projection_invalid_plane(block):
    with pytest.raises(ValueError):
        OP.projection(block, "AB")


def test_boundary_perimeter(block):
    assert OP.boundary(block, "XY").length == pytest.approx(60.0)  # 2*(10+20)


# --- OBB -------------------------------------------------------------------
def test_obb_extent_matches_box(block):
    box = OP.obb(block)
    assert sorted(round(e) for e in box.extent) == [10, 12, 20]
    assert box.center == pytest.approx((5.0, 10.0, 6.0), abs=1e-6)


# --- boolean set operators (2D) --------------------------------------------
def test_boolean_operators():
    a = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    b = Polygon([(2, 2), (6, 2), (6, 6), (2, 6)])
    assert OP.union(a, b).area == pytest.approx(28.0)      # 16 + 16 - 4
    assert OP.intersect(a, b).area == pytest.approx(4.0)
    assert OP.subtract(a, b).area == pytest.approx(12.0)


def test_boolean_3d_prisms(block):
    other = OP.extrude(Polygon([(5, 5), (15, 5), (15, 15), (5, 15)]), (0, 0, 1), 12.0)
    assert OP.union(block, other).volume() == pytest.approx(3000.0)     # (200+100-50)*12
    assert OP.intersect(block, other).volume() == pytest.approx(600.0)  # 50*12
    assert OP.subtract(block, other).volume() == pytest.approx(1800.0)  # 150*12


def test_boolean_3d_rejects_non_prism(block):
    skewed = OP.Solid([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                      [[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]])
    with pytest.raises(NotImplementedError):
        OP._prism_boolean(block, skewed, "union")


# --- VOID ------------------------------------------------------------------
def test_void_filters_openings():
    wall = {
        "ifc_type": "IfcWall",
        "children": [
            {"ifc_type": "IfcWindow"},
            {"ifc_type": "IfcDoor"},
            {"ifc_type": "IfcBeam"},
        ],
    }
    voids = OP.void(wall)
    assert {v["ifc_type"] for v in voids} == {"IfcWindow", "IfcDoor"}


def test_void_on_iterable():
    objs = [{"ifc_type": "IfcWindow"}, {"ifc_type": "IfcSlab"}]
    assert [o["ifc_type"] for o in OP.void(objs)] == ["IfcWindow"]


# --- exterior / interior ---------------------------------------------------
def test_exterior_single_shell_is_self(block):
    assert OP.exterior(block).volume() == pytest.approx(block.volume())
    assert len(OP.interior(block).vertices) == 0


def test_exterior_picks_largest_shell():
    big = OP.extrude(Polygon([(0, 0), (30, 0), (30, 30), (0, 30)]), (0, 0, 1), 30)
    small = OP.extrude(Polygon([(100, 100), (102, 100), (102, 102), (100, 102)]), (0, 0, 1), 2)
    merged = OP._merge_solids([big, small])
    assert len(OP._split_shells(merged)) == 2
    assert OP.exterior(merged).volume() == pytest.approx(27000.0)  # 30^3
    assert OP.interior(merged).volume() == pytest.approx(8.0)      # 2^3


# --- Solid serialisation ---------------------------------------------------
def test_solid_to_obj_roundtrip(block, tmp_path):
    path = block.save_obj(str(tmp_path / "block.obj"))
    text = open(path, encoding="utf-8").read()
    assert text.count("\nv ") + text.startswith("v ") >= 8  # 8 vertices
    assert "f " in text  # has faces, 1-indexed


# --- high-level LOD1 -------------------------------------------------------
def test_generate_lod1(square):
    solid = OP.generate_lod1(square, height=9.0)
    assert solid.volume() == pytest.approx(200.0 * 9.0)


def test_apply_operator_registry(square):
    fp = OP.apply_operator("footprint", square)
    assert fp.area == pytest.approx(200.0)
    with pytest.raises(KeyError):
        OP.apply_operator("nonexistent", square)


# --- 3D booleans at projected coordinates -----------------------------------
PROJECTED = (-9755973.4149, 5142153.8439)   # the sample's EPSG:3857 origin


def _shift(solid, dx, dy):
    verts = solid.vertices.copy()
    verts[:, 0] += dx
    verts[:, 1] += dy
    return OP.Solid(verts, solid.faces)


@pytest.fixture
def thin_wall():
    """A wall at the sample's real size: 1.135 x 0.054 x 2.6 m."""
    return OP.extrude(Polygon([(0, 0), (1.135, 0), (1.135, 0.054), (0, 0.054)]),
                      (0, 0, 1), 2.6)


@pytest.fixture
def opening():
    return OP.extrude(Polygon([(0.3, -0.1), (0.8, -0.1), (0.8, 0.154), (0.3, 0.154)]),
                      (0, 0, 1), 1.2)


def test_boolean_survives_projected_coordinates(thin_wall, opening):
    """float32 resolves to about a metre at EPSG:3857 magnitudes and would erase
    a 54 mm wall, so the mesh backend has to carry doubles through."""
    pytest.importorskip("manifold3d")
    expected = 1.135 * 0.054 * 2.6 - 0.5 * 0.054 * 1.2
    local = OP.subtract(thin_wall, opening)
    projected = OP.subtract(_shift(thin_wall, *PROJECTED), _shift(opening, *PROJECTED))
    assert local.volume() == pytest.approx(expected, rel=1e-6)
    assert projected.volume() == pytest.approx(expected, rel=1e-6)


def test_volume_is_translation_invariant(thin_wall):
    """The divergence-theorem sum loses its significant digits at 1e7 unless the
    coordinates are centred first. Centring leaves a residual around 1e-8
    relative, against 2e-2 without it."""
    here = thin_wall.volume()
    there = _shift(thin_wall, *PROJECTED).volume()
    assert there == pytest.approx(here, rel=1e-7)


def test_mesh_backend_handles_non_prisms(block):
    """The prism fallback refuses these; the mesh backend does not."""
    pytest.importorskip("manifold3d")
    tetra = OP.Solid([[20, 20, 0], [21, 20, 0], [20, 21, 0], [20, 20, 1]],
                     [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
    assert OP.union(block, tetra).volume() == pytest.approx(2400 + 1 / 6, rel=1e-6)


def test_disjoint_intersection_is_empty(block):
    pytest.importorskip("manifold3d")
    far = OP.extrude(Polygon([(100, 100), (110, 100), (110, 110), (100, 110)]),
                     (0, 0, 1), 5.0)
    result = OP.intersect(block, far)
    assert len(result.faces) == 0 and result.volume() == 0.0


def test_boolean_result_stays_closed(block):
    """CityGML 3.0 writes gml:Solid only for a closed shell, so a boolean result
    must keep that property."""
    pytest.importorskip("manifold3d")
    import B2GM_citygml3

    other = OP.extrude(Polygon([(5, 5), (15, 5), (15, 15), (5, 15)]), (0, 0, 1), 12.0)
    brep = OP.to_brep(OP.union(block, other))
    assert B2GM_citygml3.is_closed_shell(brep)
