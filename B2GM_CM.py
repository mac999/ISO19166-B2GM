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

This module provides the CRS transform (via :mod:`pyproj`) and helpers to read
the georeferencing of an IFC ``IfcSite`` (its ``RefLatitude`` / ``RefLongitude``
expressed as degree/minute/second tuples).

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # pyproj is a light dependency and is expected to be present
    from pyproj import Transformer

    _HAVE_PYPROJ = True
except Exception:  # pragma: no cover - defensive
    _HAVE_PYPROJ = False


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
    ):
        self.source_crs = source_crs
        self.dest_crs = dest_crs
        self.transform_matrix = transform_matrix

    @classmethod
    def from_stage(cls, stage: Dict[str, Any]) -> "CoordinateMapping":
        source = "EPSG:4326"
        dest = "EPSG:3857"
        matrix = None
        for rule in stage.get("rule", []):
            if "source" in rule and "destination" in rule:
                source = rule["source"]
                dest = rule["destination"]
            # note: original sample data misspells the key as "tranform_matrix"
            if "transform_matrix" in rule:
                matrix = rule["transform_matrix"]
            elif "tranform_matrix" in rule:
                matrix = rule["tranform_matrix"]
        return cls(source, dest, matrix)

    def transform(self, x: float, y: float) -> Tuple[float, float]:
        return transform_coordinate(x, y, self.source_crs, self.dest_crs)


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
    """Compute the georeferencing of ``ifc_file`` under ``mapping``.

    Returns a summary dict with the source origin (lon/lat) and the projected
    origin in the destination CRS.  The IFC geometry itself is left untouched;
    the summary is what downstream GIS serialisation needs.
    """
    origin = read_ifc_origin(ifc_file)
    summary: Dict[str, Any] = {
        "source_crs": mapping.source_crs,
        "dest_crs": mapping.dest_crs,
        "source_origin": None,
        "dest_origin": None,
    }
    if origin is None:
        return summary
    lon, lat, elev = origin
    summary["source_origin"] = {"lon": lon, "lat": lat, "elevation": elev}
    try:
        px, py = mapping.transform(lon, lat)
        summary["dest_origin"] = {"x": px, "y": py, "elevation": elev}
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
