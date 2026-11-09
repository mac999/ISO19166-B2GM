"""
B2GM CM - Coordinate Mapping (ISO 19166 B2GM).

Coordinate Mapping transforms the source (BIM) coordinate reference system to
the destination (GIS) CRS.  A pipeline CM stage looks like::

    {
      "type": "CM",
      "rule": [
        {"source": "EPSG:4326", "destination": "EPSG:3857"},
        {"tranform_matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}
      ]
    }

This module provides the CRS transform (via :mod:`pyproj`), helpers to read
the georeferencing an IFC carries and the :class:`Placement` that moves IFC
local metres into the destination CRS so the emitted CityGML is georeferenced.

Three sources of georeferencing are recognised, in this order of precedence:

* an explicit ``origin`` in the CM stage of the pipeline;
* ``IfcMapConversion`` + ``IfcProjectedCRS`` (IFC4 Add2 and later), or the
  ``ePSet_MapConversion`` / ``ePSet_ProjectedCRS`` property sets that carry the
  same fields in IFC2x3 files: eastings, northings, orthogonal height, the
  map-grid direction of the local X axis and a scale, with the projected CRS
  named by its EPSG code;
* ``IfcSite`` ``RefLatitude`` / ``RefLongitude`` / ``RefElevation``, the
  weakest form, where the point sits at the site's own placement, so the site's
  ``ObjectPlacement`` is undone before the local metres are projected.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pyproj is a light dependency and is expected to be present
    from pyproj import Transformer

    _HAVE_PYPROJ = True
except Exception:  # pragma: no cover - defensive
    _HAVE_PYPROJ = False

logger = logging.getLogger(__name__)


def dms_to_deg(dms: Sequence[float]) -> float:
    """Convert an IFC compound-plane-angle ``(deg, min, sec[, millionth])`` to degrees.

    IFC stores latitude/longitude as integer degrees, minutes, seconds and an
    optional millionth-of-a-second component.  The sign of the leading degree
    term applies to the whole value.
    """
    if not dms:
        return 0.0
    parts = list(dms)
    sign = -1.0 if parts[0] < 0 else 1.0
    deg = abs(parts[0])
    minutes = abs(parts[1]) if len(parts) > 1 else 0.0
    seconds = abs(parts[2]) if len(parts) > 2 else 0.0
    millionths = abs(parts[3]) if len(parts) > 3 else 0.0
    seconds = seconds + millionths / 1_000_000.0
    return sign * (deg + minutes / 60.0 + seconds / 3600.0)


def transform_coordinate(
    x: float, y: float, src_crs: str, dst_crs: str, always_xy: bool = True
) -> Tuple[float, float]:
    """Transform a single (x, y) coordinate from ``src_crs`` to ``dst_crs``.

    ``x``/``y`` follow the ``always_xy`` convention: for geographic CRS pass
    ``x = longitude`` and ``y = latitude``.
    """
    if not _HAVE_PYPROJ:
        raise RuntimeError("pyproj is required for coordinate transformation")
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=always_xy)
    return transformer.transform(x, y)


class CoordinateMapping:
    """Coordinate mapping rule (source/destination CRS + optional matrix)."""

    def __init__(
        self,
        source_crs: str = "EPSG:4326",
        dest_crs: str = "EPSG:3857",
        transform_matrix: Optional[List[List[float]]] = None,
        origin: Optional[Tuple[float, float, float]] = None,
        georeference: bool = True,
    ):
        self.source_crs = source_crs
        self.dest_crs = dest_crs
        self.transform_matrix = transform_matrix
        # explicit origin for an IFC without IfcSite georeferencing
        self.origin = origin
        self.georeference = georeference

    @classmethod
    def from_stage(cls, stage: Dict[str, Any]) -> "CoordinateMapping":
        source = "EPSG:4326"
        dest = "EPSG:3857"
        matrix = None
        origin = None
        for rule in stage.get("rule", []):
            if "source" in rule and "destination" in rule:
                source = rule["source"]
                dest = rule["destination"]
            # note: original sample data misspells the key as "tranform_matrix"
            if "transform_matrix" in rule:
                matrix = rule["transform_matrix"]
            elif "tranform_matrix" in rule:
                matrix = rule["tranform_matrix"]
            if "rotation" in rule:
                # degrees about Z, counter-clockwise seen from above, applied
                # before any transform_matrix: the easy way to turn a model
                # along a street when it is placed by hand
                matrix = compose(matrix, rotation_matrix(float(rule["rotation"])))
            if "origin" in rule:
                spot = rule["origin"]
                origin = (float(spot["lon"]), float(spot["lat"]),
                          float(spot.get("elevation", 0.0)))
        return cls(source, dest, matrix, origin, stage.get("georeference", True))

    def transform(self, x: float, y: float) -> Tuple[float, float]:
        return transform_coordinate(x, y, self.source_crs, self.dest_crs)


def rotation_matrix(degrees: float) -> List[List[float]]:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[c, -s, 0.0, 0.0], [s, c, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def compose(outer: Optional[List[List[float]]], inner: List[List[float]]) -> List[List[float]]:
    """``outer @ inner``: ``inner`` is applied first."""
    if not outer:
        return inner
    return [[sum(outer[i][k] * inner[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _apply_matrix(m: Optional[List[List[float]]], x: float, y: float, z: float
                  ) -> Tuple[float, float, float]:
    if not m:
        return x, y, z
    return (
        m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
        m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
        m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
    )


def invert_matrix(m: List[List[float]]) -> List[List[float]]:
    import numpy as np

    return np.linalg.inv(np.array(m, dtype=float)).tolist()


def is_identity(m: Optional[List[List[float]]], tol: float = 1e-9) -> bool:
    if not m:
        return True
    for i in range(4):
        for j in range(4):
            if abs(float(m[i][j]) - (1.0 if i == j else 0.0)) > tol:
                return False
    return True


class Placement:
    """Moves IFC local metres into the destination CRS.

    The chain is: ``pre_matrix`` (undoes the ``IfcSite`` placement when the
    georeferencing point is the site's own origin), the stage's 4x4
    ``transform_matrix``, then one of two ways onto the map:

    * with a map conversion, the IFC's own eastings / northings / rotation /
      scale put the local metres straight into the IFC's projected CRS;
    * otherwise the true-north rotation (IFC +Y is project north) and a
      transverse-Mercator CRS centred on the geographic origin, which makes the
      local metres directly usable as projected coordinates;

    and finally pyproj into the destination CRS.
    """

    def __init__(self, origin: Tuple[float, float, float], dest_crs: str,
                 true_north: Tuple[float, float] = (0.0, 1.0),
                 transform_matrix: Optional[List[List[float]]] = None,
                 pre_matrix: Optional[List[List[float]]] = None,
                 map_conversion: Optional[Dict[str, Any]] = None):
        if not _HAVE_PYPROJ:
            raise RuntimeError("pyproj is required to georeference the model")
        self.origin = origin
        self.dest_crs = dest_crs
        self.transform_matrix = transform_matrix
        self.pre_matrix = None if is_identity(pre_matrix) else pre_matrix
        self.map_conversion = map_conversion
        lon, lat, self.elevation = origin
        length = math.hypot(*true_north) or 1.0
        self.north = (true_north[0] / length, true_north[1] / length)
        if map_conversion:
            self.local_crs = map_conversion["crs"]
            self.elevation = float(map_conversion.get("height", 0.0))
        else:
            self.local_crs = (f"+proj=tmerc +lat_0={lat} +lon_0={lon} +k=1 "
                              "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs")
        self._transformer = Transformer.from_crs(self.local_crs, dest_crs, always_xy=True)

    def _matrix(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        x, y, z = _apply_matrix(self.pre_matrix, x, y, z)
        return _apply_matrix(self.transform_matrix, x, y, z)

    def point(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        x, y, z = self._matrix(x, y, z)
        mc = self.map_conversion
        if mc:
            # the local X axis points along (abscissa, ordinate) on the map grid
            a, o, s = mc["x_axis"][0], mc["x_axis"][1], mc.get("scale", 1.0)
            east = mc["eastings"] + s * (a * x - o * y)
            north = mc["northings"] + s * (o * x + a * y)
        else:
            nx, ny = self.north
            east = x * ny - y * nx
            north = x * nx + y * ny
        px, py = self._transformer.transform(east, north)
        return px, py, z + self.elevation

    def points(self, flat: Sequence[float]) -> List[float]:
        """Transform a flat ``[x, y, z, x, y, z, ...]`` vertex list."""
        out: List[float] = []
        for i in range(0, len(flat) - 2, 3):
            out.extend(self.point(float(flat[i]), float(flat[i + 1]), float(flat[i + 2])))
        return out

    def to_dict(self) -> Dict[str, Any]:
        lon, lat, elev = self.origin
        out = {
            "origin": {"lon": lon, "lat": lat, "elevation": elev},
            "true_north": list(self.north),
            "dest_crs": self.dest_crs,
            "transform_matrix": self.transform_matrix,
        }
        if self.map_conversion:
            out["map_conversion"] = self.map_conversion
        if self.pre_matrix:
            out["site_placement_undone"] = True
        return out


def apply_placement(objects: Iterable[Dict[str, Any]], placement: Placement,
                    seen: Optional[set] = None) -> int:
    """Rewrite every element's B-rep into the destination CRS; returns the count.

    EM and LM hand out shallow copies that share the source geometry dict, and
    an LM operator result sits in ``_lod_geometry``; ``seen`` keeps a geometry
    from being projected twice when several lists are passed in turn.
    """
    moved = 0
    seen = set() if seen is None else seen
    for obj in objects:
        counted = False
        for key in ("geometry", "_lod_geometry"):
            geometry = obj.get(key) or {}
            verts = geometry.get("verts")
            if not verts or id(geometry) in seen:
                continue
            geometry["verts"] = placement.points(verts)
            seen.add(id(geometry))
            counted = True
        if counted:
            moved += 1
    return moved


def length_unit_scale(ifc_file) -> float:
    """Factor from the file's length unit to metres (1.0 when unknown).

    ifcopenshell's geometry engine already returns metres, but placements and
    ``IfcLengthMeasure`` attributes are in the project's own unit."""
    try:
        from ifcopenshell.util.unit import calculate_unit_scale

        return float(calculate_unit_scale(ifc_file))
    except Exception:
        return 1.0


def read_map_conversion(ifc_file) -> Optional[Dict[str, Any]]:
    """The IFC's own map conversion, or ``None``.

    IFC4 Add2 and later carry ``IfcMapConversion`` whose ``TargetCRS`` is an
    ``IfcProjectedCRS`` named by EPSG code.  IFC2x3 files follow the
    buildingSMART guideline instead and put the same fields in property sets
    named ``ePSet_MapConversion`` and ``ePSet_ProjectedCRS``.  Both come back
    as ``{eastings, northings, height, x_axis: (abscissa, ordinate), scale,
    crs}``; a conversion whose CRS pyproj cannot resolve is reported as absent.
    """
    found: Dict[str, Any] = {}
    try:
        conversions = ifc_file.by_type("IfcMapConversion")
    except Exception:
        conversions = []
    for mc in conversions:
        target = getattr(mc, "TargetCRS", None)
        found = {
            "eastings": float(mc.Eastings or 0.0),
            "northings": float(mc.Northings or 0.0),
            "height": float(mc.OrthogonalHeight or 0.0),
            "x_axis": (float(mc.XAxisAbscissa if mc.XAxisAbscissa is not None else 1.0),
                       float(mc.XAxisOrdinate if mc.XAxisOrdinate is not None else 0.0)),
            "scale": float(mc.Scale if mc.Scale is not None else 1.0),
            "crs": getattr(target, "Name", None),
            "source": "IfcMapConversion",
        }
        break
    if not found:
        props: Dict[str, Any] = {}
        crs_name = None
        try:
            psets = ifc_file.by_type("IfcPropertySet")
        except Exception:
            psets = []
        for pset in psets:
            name = (pset.Name or "")
            lowered = name.lower()
            if "mapconversion" not in lowered and "projectedcrs" not in lowered:
                continue
            for prop in pset.HasProperties or []:
                if not prop.is_a("IfcPropertySingleValue") or prop.NominalValue is None:
                    continue
                value = prop.NominalValue.wrappedValue
                if "projectedcrs" in lowered and prop.Name == "Name":
                    crs_name = str(value)
                elif "mapconversion" in lowered:
                    props[prop.Name] = value
        if "Eastings" in props and "Northings" in props:
            found = {
                "eastings": float(props["Eastings"]),
                "northings": float(props["Northings"]),
                "height": float(props.get("OrthogonalHeight", 0.0) or 0.0),
                "x_axis": (float(props.get("XAxisAbscissa", 1.0) or 1.0),
                           float(props.get("XAxisOrdinate", 0.0) or 0.0)),
                "scale": float(props.get("Scale", 1.0) or 1.0),
                "crs": crs_name,
                "source": "ePSet_MapConversion",
            }
    if not found:
        return None
    if not found.get("crs"):
        logger.warning("%s has no projected CRS name; ignored", found["source"])
        return None
    # lengths are in the project unit; the map grid and the geometry are metres
    scale = length_unit_scale(ifc_file)
    for key in ("eastings", "northings", "height"):
        found[key] = found[key] * scale
    try:
        Transformer.from_crs(found["crs"], "EPSG:4326", always_xy=True)
    except Exception as exc:
        logger.warning("%s names a CRS pyproj cannot resolve (%s): %s",
                       found["source"], found["crs"], exc)
        return None
    length = math.hypot(*found["x_axis"]) or 1.0
    found["x_axis"] = (found["x_axis"][0] / length, found["x_axis"][1] / length)
    return found


def read_site_placement(ifc_file) -> Optional[List[List[float]]]:
    """The first ``IfcSite``'s placement as a 4x4 matrix, or ``None``."""
    try:
        from ifcopenshell.util.placement import get_local_placement

        for site in ifc_file.by_type("IfcSite"):
            if site.ObjectPlacement is not None:
                matrix = get_local_placement(site.ObjectPlacement)
                scale = length_unit_scale(ifc_file)
                for row in range(3):
                    matrix[row][3] *= scale       # translation in project units -> metres
                return matrix.tolist()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("could not read the IfcSite placement: %s", exc)
    return None


def read_true_north(ifc_file) -> Tuple[float, float]:
    """Return the IFC ``TrueNorth`` direction, defaulting to project +Y."""
    try:
        contexts = ifc_file.by_type("IfcGeometricRepresentationContext")
    except Exception:
        return (0.0, 1.0)
    for context in contexts:
        direction = getattr(context, "TrueNorth", None)
        ratios = getattr(direction, "DirectionRatios", None) if direction else None
        if ratios and len(ratios) >= 2:
            return (float(ratios[0]), float(ratios[1]))
    return (0.0, 1.0)


def read_ifc_origin(ifc_file) -> Optional[Tuple[float, float, float]]:
    """Return the georeferenced origin ``(lon, lat, elevation)`` of an IFC file.

    Uses the first ``IfcSite`` that carries ``RefLatitude`` / ``RefLongitude``.
    Returns ``None`` when the file is not georeferenced.
    """
    try:
        sites = ifc_file.by_type("IfcSite")
    except Exception:
        return None
    for site in sites:
        lat = getattr(site, "RefLatitude", None)
        lon = getattr(site, "RefLongitude", None)
        if lat and lon:
            elevation = getattr(site, "RefElevation", 0.0) or 0.0
            return (dms_to_deg(lon), dms_to_deg(lat), float(elevation))
    return None


def apply_to_ifc(ifc_file, mapping: CoordinateMapping) -> Dict[str, Any]:
    """Georeference ``ifc_file`` under ``mapping``.

    Returns a summary with the source origin (lon/lat), the projected origin and
    the :class:`Placement` (under ``"placement"``) that moves the model geometry
    into the destination CRS.
    """
    summary: Dict[str, Any] = {
        "source_crs": mapping.source_crs,
        "dest_crs": mapping.dest_crs,
        "source_origin": None,
        "dest_origin": None,
        "placement": None,
    }
    map_conversion = None if mapping.origin else read_map_conversion(ifc_file)
    pre_matrix = None
    if mapping.origin:
        origin = mapping.origin
        summary["georeference_source"] = "pipeline origin"
    elif map_conversion:
        # the conversion's own origin, expressed geographically for the record
        lon, lat = transform_coordinate(map_conversion["eastings"], map_conversion["northings"],
                                        map_conversion["crs"], "EPSG:4326")
        origin = (lon, lat, map_conversion["height"])
        summary["map_conversion"] = map_conversion
        summary["georeference_source"] = map_conversion["source"]
        if mapping.source_crs != map_conversion["crs"]:
            logger.info("CM source CRS %s replaced by the IFC's own %s",
                        mapping.source_crs, map_conversion["crs"])
            summary["source_crs"] = map_conversion["crs"]
    else:
        origin = read_ifc_origin(ifc_file)
        summary["georeference_source"] = "IfcSite"
        # the lat/lon belong to the site's placement point, so world
        # coordinates must be taken back to the site first
        site = read_site_placement(ifc_file)
        if site and not is_identity(site):
            pre_matrix = invert_matrix(site)
            summary["site_placement"] = site
    if origin is None:
        logger.warning("IFC has no georeferencing; model stays in local coordinates")
        summary["georeference_source"] = None
        return summary
    lon, lat, elev = origin
    true_north = read_true_north(ifc_file)
    summary["source_origin"] = {"lon": lon, "lat": lat, "elevation": elev}
    summary["true_north"] = list(true_north)
    try:
        px, py = transform_coordinate(lon, lat, "EPSG:4326", mapping.dest_crs)
        summary["dest_origin"] = {"x": px, "y": py, "elevation": elev}
        if mapping.georeference:
            summary["placement"] = Placement(origin, mapping.dest_crs, true_north,
                                             mapping.transform_matrix, pre_matrix,
                                             map_conversion)
    except Exception as exc:  # pragma: no cover - defensive
        summary["error"] = str(exc)
    return summary


def from_stage(stage: Dict[str, Any]) -> CoordinateMapping:
    return CoordinateMapping.from_stage(stage)


if __name__ == "__main__":
    cm = CoordinateMapping("EPSG:4326", "EPSG:3857")
    # Chicago-ish point
    print(cm.transform(-87.639, 41.874))
    print(dms_to_deg((41, 52, 27, 840000)))
