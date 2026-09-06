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

This module provides the CRS transform (via :mod:`pyproj`), helpers to read the
georeferencing of an IFC ``IfcSite`` (its ``RefLatitude`` / ``RefLongitude``
expressed as degree/minute/second tuples) and the :class:`Placement` that moves
IFC local metres into the destination CRS so the emitted CityGML is
georeferenced.

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
            if "origin" in rule:
                spot = rule["origin"]
                origin = (float(spot["lon"]), float(spot["lat"]),
                          float(spot.get("elevation", 0.0)))
        return cls(source, dest, matrix, origin, stage.get("georeference", True))

    def transform(self, x: float, y: float) -> Tuple[float, float]:
        return transform_coordinate(x, y, self.source_crs, self.dest_crs)


class Placement:
    """Moves IFC local metres into the destination CRS.

    The IFC model is metres relative to its project origin, so the chain is:
    the stage's 4x4 ``transform_matrix``, then the true-north rotation (IFC +Y
    is project north), then a transverse-Mercator CRS centred on the site origin
    -- which makes the local metres directly usable as projected coordinates --
    and finally pyproj into the destination CRS.
    """

    def __init__(self, origin: Tuple[float, float, float], dest_crs: str,
                 true_north: Tuple[float, float] = (0.0, 1.0),
                 transform_matrix: Optional[List[List[float]]] = None):
        if not _HAVE_PYPROJ:
            raise RuntimeError("pyproj is required to georeference the model")
        self.origin = origin
        self.dest_crs = dest_crs
        self.transform_matrix = transform_matrix
        lon, lat, self.elevation = origin
        length = math.hypot(*true_north) or 1.0
        self.north = (true_north[0] / length, true_north[1] / length)
        self.local_crs = (f"+proj=tmerc +lat_0={lat} +lon_0={lon} +k=1 "
                          "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs")
        self._transformer = Transformer.from_crs(self.local_crs, dest_crs, always_xy=True)

    def _matrix(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        m = self.transform_matrix
        if not m:
            return x, y, z
        return (
            m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
        )

    def point(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        x, y, z = self._matrix(x, y, z)
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
        return {
            "origin": {"lon": lon, "lat": lat, "elevation": elev},
            "true_north": list(self.north),
            "dest_crs": self.dest_crs,
            "transform_matrix": self.transform_matrix,
        }


def apply_placement(objects: Iterable[Dict[str, Any]], placement: Placement) -> int:
    """Rewrite every element's B-rep into the destination CRS; returns the count."""
    moved = 0
    for obj in objects:
        geometry = obj.get("geometry") or {}
        verts = geometry.get("verts")
        if not verts:
            continue
        geometry["verts"] = placement.points(verts)
        moved += 1
    return moved


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
    origin = mapping.origin or read_ifc_origin(ifc_file)
    summary: Dict[str, Any] = {
        "source_crs": mapping.source_crs,
        "dest_crs": mapping.dest_crs,
        "source_origin": None,
        "dest_origin": None,
        "placement": None,
    }
    if origin is None:
        logger.warning("IFC has no IfcSite georeferencing; model stays in local coordinates")
        return summary
    lon, lat, elev = origin
    true_north = read_true_north(ifc_file)
    summary["source_origin"] = {"lon": lon, "lat": lat, "elevation": elev}
    summary["true_north"] = list(true_north)
    try:
        px, py = mapping.transform(lon, lat)
        summary["dest_origin"] = {"x": px, "y": py, "elevation": elev}
        if mapping.georeference:
            summary["placement"] = Placement(origin, mapping.dest_crs, true_north,
                                             mapping.transform_matrix)
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
