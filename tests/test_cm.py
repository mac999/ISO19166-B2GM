"""Tests for the Coordinate Mapping (CM) stage."""

import pytest

import B2GM_CM as CM


def test_dms_to_deg_positive():
    # 41 deg 52' 27.84" -> 41.8744
    assert CM.dms_to_deg((41, 52, 27, 840000)) == pytest.approx(41.8744, abs=1e-4)


def test_dms_to_deg_negative_sign_propagates():
    # -87 deg 38' 21.84" -> -87.6394
    val = CM.dms_to_deg((-87, -38, -21, -839999))
    assert val == pytest.approx(-87.6394, abs=1e-4)
    assert val < 0


def test_transform_coordinate_wgs84_to_webmercator():
    x, y = CM.transform_coordinate(-87.6394, 41.8744, "EPSG:4326", "EPSG:3857")
    # Chicago in Web Mercator (meters)
    assert x == pytest.approx(-9_755_970, abs=2000)
    assert y == pytest.approx(5_142_180, abs=2000)


def test_coordinate_mapping_from_stage_handles_typo():
    stage = {
        "rule": [
            {"source": "EPSG:4326", "destination": "EPSG:3857"},
            {"tranform_matrix": [[1, 0, 0, 0]]},  # original misspelled key
        ]
    }
    cm = CM.CoordinateMapping.from_stage(stage)
    assert cm.source_crs == "EPSG:4326"
    assert cm.dest_crs == "EPSG:3857"
    assert cm.transform_matrix == [[1, 0, 0, 0]]


def test_read_ifc_origin_and_apply(sample_ifc):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    ifc = ifcopenshell.open(sample_ifc)

    origin = CM.read_ifc_origin(ifc)
    assert origin is not None
    lon, lat, _elev = origin
    assert lat == pytest.approx(41.8744, abs=1e-3)
    assert lon == pytest.approx(-87.6394, abs=1e-3)

    cm = CM.CoordinateMapping("EPSG:4326", "EPSG:3857")
    summary = CM.apply_to_ifc(ifc, cm)
    assert summary["dest_origin"]["x"] == pytest.approx(-9_755_970, abs=5000)


# --- geometry placement (CM actually moves the model) ------------------------
import math

import pytest


def _placement(lon=-87.6394, lat=41.8744, elevation=0.0, **kwargs):
    return CM.Placement((lon, lat, elevation), "EPSG:3857", **kwargs)


def test_placement_puts_the_origin_on_the_site():
    place = _placement()
    x, y, z = place.point(0, 0, 0)
    expected = CM.transform_coordinate(-87.6394, 41.8744, "EPSG:4326", "EPSG:3857")
    assert (x, y) == pytest.approx(expected)
    assert z == 0.0


def test_placement_keeps_ground_distance_after_mercator_scale():
    place = _placement()
    origin = place.point(0, 0, 0)
    east = place.point(100.0, 0, 0)
    north = place.point(0, 100.0, 0)
    # Web Mercator inflates distance by 1/cos(lat); dividing it out returns metres.
    # EPSG:3857 projects geodetic latitude on a sphere, so ~0.2% remains.
    k = 1.0 / math.cos(math.radians(41.8744))
    assert (east[0] - origin[0]) / k == pytest.approx(100.0, rel=3e-3)
    assert (north[1] - origin[1]) / k == pytest.approx(100.0, rel=3e-3)


def test_placement_adds_the_site_elevation():
    assert _placement(elevation=12.5).point(0, 0, 3.0)[2] == pytest.approx(15.5)


def test_placement_applies_true_north_rotation():
    # true north along +X means the model's +X is north, so +X must move north
    rotated = _placement(true_north=(1.0, 0.0))
    origin = rotated.point(0, 0, 0)
    moved = rotated.point(100.0, 0, 0)
    assert moved[1] - origin[1] > 100.0      # northing grew
    assert moved[0] == pytest.approx(origin[0], abs=1e-6)


def test_placement_applies_the_transform_matrix():
    shifted = _placement(transform_matrix=[[1, 0, 0, 10], [0, 1, 0, 0],
                                           [0, 0, 1, 5], [0, 0, 0, 1]])
    plain = _placement()
    assert shifted.point(0, 0, 0)[0] == pytest.approx(plain.point(10, 0, 0)[0])
    assert shifted.point(0, 0, 0)[2] == pytest.approx(5.0)


def test_apply_placement_rewrites_element_geometry():
    objects = [
        {"geometry": {"verts": [0, 0, 0, 10, 0, 0], "faces": [0, 1, 0]}},
        {"name": "no geometry"},
    ]
    moved = CM.apply_placement(objects, _placement())
    assert moved == 1
    verts = objects[0]["geometry"]["verts"]
    assert len(verts) == 6 and verts[0] < -9_000_000     # now in EPSG:3857


def test_stage_reads_origin_override_and_switch():
    mapping = CM.CoordinateMapping.from_stage({
        "georeference": False,
        "rule": [{"source": "EPSG:4326", "destination": "EPSG:5186"},
                 {"origin": {"lon": 126.98, "lat": 37.56, "elevation": 20.0}}],
    })
    assert mapping.dest_crs == "EPSG:5186"
    assert mapping.origin == (126.98, 37.56, 20.0)
    assert mapping.georeference is False


def test_placement_works_for_a_projected_national_crs():
    # EPSG:5186 (Korea Central Belt 2010) - a metric CRS with no mercator inflation
    place = CM.Placement((126.9780, 37.5665, 0.0), "EPSG:5186")
    origin = place.point(0, 0, 0)
    east = place.point(100.0, 0, 0)
    assert east[0] - origin[0] == pytest.approx(100.0, rel=1e-3)


# --- georeferencing sources beyond IfcSite ----------------------------------
def _ifc4_with_site(site_offset=(0.0, 0.0, 0.0)):
    import numpy as np
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.api
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    import ifcopenshell.api.project
    import ifcopenshell.api.root
    import ifcopenshell.api.unit

    f = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "METERS"})
    context = ifcopenshell.api.context.add_context(f, context_type="Model")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="s")
    site.RefLatitude = (37, 33, 0, 0)
    site.RefLongitude = (126, 58, 0, 0)
    site.RefElevation = 0.0
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    m = np.eye(4)
    m[:3, 3] = site_offset
    ifcopenshell.api.geometry.edit_object_placement(f, product=site, matrix=m)
    return f, context


def test_ifc4_map_conversion_places_local_metres_on_the_named_grid():
    f, context = _ifc4_with_site()
    crs = f.createIfcProjectedCRS("EPSG:25832")
    # local +X points along map north: abscissa 0, ordinate 1
    f.createIfcMapConversion(context, crs, 500000.0, 5600000.0, 100.0, 0.0, 1.0, 1.0)

    found = CM.read_map_conversion(f)
    assert found and found["crs"] == "EPSG:25832" and found["source"] == "IfcMapConversion"

    summary = CM.apply_to_ifc(f, CM.CoordinateMapping("EPSG:4326", "EPSG:25832"))
    assert summary["georeference_source"] == "IfcMapConversion"
    assert summary["source_crs"] == "EPSG:25832"
    placement = summary["placement"]
    x, y, z = placement.point(10.0, 0.0, 2.0)
    assert abs(x - 500000.0) < 1e-6 and abs(y - 5600010.0) < 1e-6 and abs(z - 102.0) < 1e-9
    x, y, _ = placement.point(0.0, 10.0, 0.0)
    assert abs(x - 499990.0) < 1e-6 and abs(y - 5600000.0) < 1e-6

    # and on to a different destination through pyproj
    to_geo = CM.apply_to_ifc(f, CM.CoordinateMapping("EPSG:4326", "EPSG:4326"))["placement"]
    lon, lat, _ = to_geo.point(0.0, 0.0, 0.0)
    assert 8.9 < lon < 9.1 and 50.4 < lat < 50.6


def test_epset_map_conversion_is_read_too():
    """IFC2x3 files carry the conversion in ePSet_* property sets; the reader
    only looks at the set names, so an IFC4 file serves to exercise it."""
    ifcopenshell = pytest.importorskip("ifcopenshell")
    f, _ = _ifc4_with_site()

    def single(name, value, kind):
        return f.createIfcPropertySingleValue(name, None, f.create_entity(kind, value), None)

    f.createIfcPropertySet(ifcopenshell.guid.new(), None, "ePSet_MapConversion", None, [
        single("Eastings", 300000.0, "IfcLengthMeasure"),
        single("Northings", 4000000.0, "IfcLengthMeasure"),
        single("OrthogonalHeight", 20.0, "IfcLengthMeasure"),
        single("XAxisAbscissa", 1.0, "IfcReal"),
        single("XAxisOrdinate", 0.0, "IfcReal"),
        single("Scale", 1.0, "IfcReal"),
    ])
    f.createIfcPropertySet(ifcopenshell.guid.new(), None, "ePSet_ProjectedCRS", None, [
        single("Name", "EPSG:32652", "IfcLabel"),
    ])
    found = CM.read_map_conversion(f)
    assert found["source"] == "ePSet_MapConversion"
    assert found["eastings"] == 300000.0 and found["crs"] == "EPSG:32652"


def test_map_conversion_lengths_follow_the_project_unit():
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.api.unit
    f, context = _ifc4_with_site()
    ifcopenshell.api.unit.assign_unit(f)            # millimetres
    crs = f.createIfcProjectedCRS("EPSG:25832")
    f.createIfcMapConversion(context, crs, 500000000.0, 5600000000.0, 100000.0, 1.0, 0.0, 1.0)
    found = CM.read_map_conversion(f)
    assert abs(found["eastings"] - 500000.0) < 1e-6 and abs(found["height"] - 100.0) < 1e-9


def test_unresolvable_projected_crs_is_ignored():
    f, context = _ifc4_with_site()
    crs = f.createIfcProjectedCRS("EPSG:999999")
    f.createIfcMapConversion(context, crs, 1.0, 2.0, 0.0, 1.0, 0.0, 1.0)
    assert CM.read_map_conversion(f) is None
    # so the site georeferencing is used instead
    assert CM.apply_to_ifc(f, CM.CoordinateMapping())["georeference_source"] == "IfcSite"


def test_site_placement_is_undone_before_projecting():
    pytest.importorskip("pyproj")
    f_at_origin, _ = _ifc4_with_site()
    f_offset, _ = _ifc4_with_site(site_offset=(100.0, 50.0, 0.0))

    plain = CM.apply_to_ifc(f_at_origin, CM.CoordinateMapping("EPSG:4326", "EPSG:3857"))
    moved = CM.apply_to_ifc(f_offset, CM.CoordinateMapping("EPSG:4326", "EPSG:3857"))
    assert "site_placement" not in plain
    assert moved["site_placement"][0][3] == 100.0
    assert moved["placement"].to_dict()["site_placement_undone"] is True

    # the world point at the offset site's origin lands where the site says it is
    x0, y0, _ = plain["placement"].point(0.0, 0.0, 0.0)
    x1, y1, _ = moved["placement"].point(100.0, 50.0, 0.0)
    assert abs(x0 - x1) < 1e-6 and abs(y0 - y1) < 1e-6


def test_apply_placement_projects_a_shared_geometry_once():
    pytest.importorskip("pyproj")
    placement = CM.Placement((126.97, 37.55, 0.0), "EPSG:3857")
    geometry = {"verts": [0.0, 0.0, 0.0], "faces": [0, 0, 0]}
    source = {"geometry": geometry}
    copy = dict(source)                      # what EM hands on
    copy["_lod_geometry"] = {"verts": [0.0, 0.0, 5.0], "faces": [0, 0, 0]}
    seen = set()
    CM.apply_placement([source], placement, seen)
    CM.apply_placement([copy], placement, seen)
    assert 1.41e7 < geometry["verts"][0] < 1.42e7       # projected exactly once
    assert 1.41e7 < copy["_lod_geometry"]["verts"][0] < 1.42e7
