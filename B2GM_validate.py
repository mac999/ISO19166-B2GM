"""Geometry validity checks for the CityGML the pipeline writes.

The writers only ever checked that a mesh closes before calling it a
``gml:Solid``; this module makes the ISO 19107-style checks explicit so a bad
solid is named instead of silently shipped:

* degenerate triangles (zero area);
* non-manifold edges (an edge used by more than two faces);
* open shells (a boundary edge on something sold as a solid);
* inconsistent orientation (two faces traversing a shared edge the same way);
* inward orientation (negative signed volume).

``citygml_errors`` re-reads a written file and validates every ``gml:Solid``
in it, so a test can assert the output is sound end to end.  When the external
`val3dity <https://github.com/tudelft3d/val3dity>`_ binary is installed,
``run_val3dity`` wraps it for the full ISO 19107 rule set; the internal checks
above do not need it.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_EPS_AREA = 1e-12


def _triangles(geometry: Dict[str, Any]) -> Tuple[np.ndarray, List[Tuple[int, int, int]]]:
    flat_v = geometry.get("verts") or []
    flat_f = geometry.get("faces") or []
    verts = np.asarray(flat_v, dtype=float).reshape(-1, 3)
    faces = [tuple(flat_f[i:i + 3]) for i in range(0, len(flat_f) - 2, 3)]
    return verts, faces


def mesh_errors(geometry: Dict[str, Any]) -> List[str]:
    """Errors every triangle mesh must be free of, closed or not."""
    verts, faces = _triangles(geometry)
    errors: List[str] = []
    if not len(faces):
        return ["mesh has no faces"]
    for n, tri in enumerate(faces):
        if max(tri) >= len(verts):
            errors.append(f"face {n} references a missing vertex")
            continue
        if len(set(tri)) < 3:
            errors.append(f"face {n} repeats a vertex")
            continue
        a, b, c = (verts[i] for i in tri)
        if np.linalg.norm(np.cross(b - a, c - a)) / 2.0 < _EPS_AREA:
            errors.append(f"face {n} is degenerate (zero area)")
    edges: Dict[Tuple[int, int], int] = {}
    for tri in faces:
        if max(tri) >= len(verts) or len(set(tri)) < 3:
            continue
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = (a, b) if a < b else (b, a)
            edges[key] = edges.get(key, 0) + 1
    bad = sum(1 for count in edges.values() if count > 2)
    if bad:
        errors.append(f"{bad} non-manifold edges (shared by more than two faces)")
    return errors


def solid_errors(geometry: Dict[str, Any]) -> List[str]:
    """``mesh_errors`` plus what a ``gml:Solid`` shell additionally requires."""
    errors = mesh_errors(geometry)
    verts, faces = _triangles(geometry)
    faces = [t for t in faces if max(t) < len(verts) and len(set(t)) == 3]
    if not faces:
        return errors

    directed: Dict[Tuple[int, int], int] = {}
    undirected: Dict[Tuple[int, int], int] = {}
    for tri in faces:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            directed[(a, b)] = directed.get((a, b), 0) + 1
            key = (a, b) if a < b else (b, a)
            undirected[key] = undirected.get(key, 0) + 1

    open_edges = sum(1 for count in undirected.values() if count == 1)
    if open_edges:
        errors.append(f"shell is not closed ({open_edges} boundary edges)")
    # a consistently oriented shell traverses every shared edge once per direction
    misoriented = sum(1 for count in directed.values() if count > 1)
    if not open_edges and misoriented:
        errors.append(f"inconsistent face orientation ({misoriented} edges"
                      " traversed twice the same way)")

    if not open_edges and not misoriented:
        volume = 0.0
        for tri in faces:
            a, b, c = (verts[i] for i in tri)
            volume += float(np.dot(a, np.cross(b, c))) / 6.0
        if volume < 0:
            errors.append("shell faces point inward (negative volume)")
    return errors


# -- validating a written CityGML file --------------------------------------
def _ring_points(poslist_text: str) -> List[Tuple[float, float, float]]:
    numbers = [float(v) for v in (poslist_text or "").split()]
    points = [tuple(numbers[i:i + 3]) for i in range(0, len(numbers) - 2, 3)]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()  # drop the closing duplicate
    return points


def _solid_geometry(solid: ET.Element) -> Dict[str, Any]:
    """Rebuild a ``{'verts', 'faces'}`` soup from a gml:Solid's polygons."""
    index: Dict[Tuple[float, float, float], int] = {}
    verts: List[float] = []
    faces: List[int] = []

    def vertex(p: Tuple[float, float, float]) -> int:
        if p not in index:
            index[p] = len(index)
            verts.extend(p)
        return index[p]

    for poly in solid.iter():
        if not poly.tag.endswith("Polygon"):
            continue
        exterior = next((c for c in poly if c.tag.endswith("exterior")), None)
        poslist = next((e for e in (exterior or poly).iter()
                        if e.tag.endswith("posList")), None)
        if poslist is None:
            continue
        ring = [vertex(p) for p in _ring_points(poslist.text)]
        for i in range(1, len(ring) - 1):  # fan triangulation
            faces.extend((ring[0], ring[i], ring[i + 1]))
    return {"verts": verts, "faces": faces}


def citygml_errors(path: str) -> List[Tuple[str, List[str]]]:
    """Validate every ``gml:Solid`` in a CityGML file.

    Returns ``[(gml_id, [error, ...]), ...]`` for the solids that fail; an
    empty list means every solid passed.
    """
    failures: List[Tuple[str, List[str]]] = []
    root = ET.parse(path).getroot()
    for element in root.iter():
        if not element.tag.endswith("}Solid"):
            continue
        gid = next((v for k, v in element.attrib.items() if k.endswith("}id")), "?")
        errors = solid_errors(_solid_geometry(element))
        if errors:
            failures.append((gid, errors))
    return failures


def run_val3dity(path: str) -> Optional[Dict[str, Any]]:
    """Run the external val3dity binary on ``path``; ``None`` when not installed."""
    binary = shutil.which("val3dity")
    if not binary:
        return None
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        report = handle.name
    subprocess.run([binary, path, "--report", report],
                   check=False, capture_output=True, timeout=600)
    with open(report, encoding="utf-8") as f:
        return json.load(f)


def main():  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(description="validate the solids of a CityGML file")
    parser.add_argument("path")
    args = parser.parse_args()
    failures = citygml_errors(args.path)
    for gid, errors in failures:
        print(f"{gid}: {'; '.join(errors)}")
    print(f"{len(failures)} invalid solids")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
