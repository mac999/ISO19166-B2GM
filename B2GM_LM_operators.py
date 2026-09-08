"""
B2G LM ruleset operators (ISO 19166 - B2G LM, Clause 9 / Table 8).

This module is a *general-purpose* implementation of the LOD-mapping operator
set the standard defines for transforming BIM geometry into GIS LODs.  Each
operator corresponds to a row of ISO 19166 "Table 8 - B2G LM class definition":

    footprint(el)                         -> geometry (2D building footprint)
    OBB(el)                               -> OBB (oriented bounding box)
    projection(g, plane{XZ,XY,YZ})        -> geometry2D
    boundary(g, plane{XZ,XY,YZ})          -> geometry2D
    extrude(g2D, v: vector3D, height)     -> geometry (solid)
    exterior(g)                           -> geometry (outer shell)
    interior(g)                           -> geometry (inner shell)
    VOID(el)                              -> element (openings: windows/doors)
    union(g1, g2)                         -> geometry
    subtract(g1, g2)                      -> geometry
    intersect(g1, g2)                     -> geometry

Geometry is represented independently of any heavy 3D library:

* 2D geometry -> :class:`shapely.geometry.Polygon` / ``MultiPolygon``
* 3D geometry -> :class:`Solid` (vertices + faces, a minimal B-rep)

Only ``numpy`` and ``shapely`` are required (both light and already used by the
project).  Nothing here is hard-coded to a particular dataset, CRS or building.

Author:
    Taewook Kang (laputa99999@gmail.com)

Date:
    2026-07 (implemented from ISO/TS 19166)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

# Reference planes: which two axes remain after projecting onto the plane.
# ZX/YX/ZY are the reversed spellings used in the standard's operator table.
PLANE_AXES: Dict[str, Tuple[int, int]] = {
    "XY": (0, 1),
    "XZ": (0, 2),
    "YZ": (1, 2),
    "YX": (0, 1),
    "ZX": (0, 2),
    "ZY": (1, 2),
}

# IFC element types that represent VOID/opening features (Table 8, VOID()).
VOID_ELEMENT_TYPES = {
    "IfcWindow",
    "IfcDoor",
    "IfcOpeningElement",
    "IfcVoidingFeature",
}


# ---------------------------------------------------------------------------
# Geometry value types
# ---------------------------------------------------------------------------
@dataclass
class Vector3D:
    """A 3D vector (``v[3]: Real`` in Table 8)."""

    v: Tuple[float, float, float] = (0.0, 0.0, 1.0)

    def as_array(self) -> np.ndarray:
        return np.asarray(self.v, dtype=float)

    def normalized(self) -> "Vector3D":
        a = self.as_array()
        n = np.linalg.norm(a)
        if n == 0:
            return Vector3D((0.0, 0.0, 0.0))
        return Vector3D(tuple(a / n))


@dataclass
class OBB:
    """Oriented bounding box (Table 8: x/y_direction + extent)."""

    center: Tuple[float, float, float]
    x_direction: Tuple[float, float, float]
    y_direction: Tuple[float, float, float]
    z_direction: Tuple[float, float, float]
    extent: Tuple[float, float, float]  # full width, depth, height

    def to_dict(self) -> Dict[str, Any]:
        return {
            "center": list(self.center),
            "x_direction": list(self.x_direction),
            "y_direction": list(self.y_direction),
            "z_direction": list(self.z_direction),
            "extent": list(self.extent),
        }


@dataclass
class Solid:
    """Minimal boundary representation: vertices + polygonal faces.

    ``vertices`` is an ``(N, 3)`` array; ``faces`` is a list of index lists (one
    per face, each referencing rows of ``vertices``).
    """

    vertices: np.ndarray
    faces: List[List[int]] = field(default_factory=list)

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, dtype=float).reshape(-1, 3)

    # -- geometry helpers ---------------------------------------------------
    def face_coords(self, face: Sequence[int]) -> np.ndarray:
        return self.vertices[list(face)]

    def bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def volume(self) -> float:
        """Signed volume via the divergence theorem (triangulated fan per face).

        Coordinates are taken relative to the centroid first: after the CM stage
        they run to 1e7, and the triple products would then cancel away most of
        the significant digits.
        """
        if len(self.vertices) == 0:
            return 0.0
        origin = self.vertices.mean(axis=0)
        vol = 0.0
        for face in self.faces:
            pts = self.face_coords(face) - origin
            if len(pts) < 3:
                continue
            v0 = pts[0]
            for i in range(1, len(pts) - 1):
                v1, v2 = pts[i], pts[i + 1]
                vol += np.dot(v0, np.cross(v1, v2)) / 6.0
        return abs(vol)

    def to_dict(self) -> Dict[str, Any]:
        return {"vertices": self.vertices.tolist(), "faces": [list(f) for f in self.faces]}

    def to_obj(self) -> str:
        """Serialise to a Wavefront OBJ string (no external dependency)."""
        lines = ["# B2GM LM Solid"]
        for x, y, z in self.vertices:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        for face in self.faces:
            lines.append("f " + " ".join(str(i + 1) for i in face))  # OBJ is 1-indexed
        return "\n".join(lines) + "\n"

    def save_obj(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_obj())
        return path

    def to_pyvista(self):  # pragma: no cover - optional viewer path
        """Convert to a pyvista.PolyData (only when pyvista is installed)."""
        import pyvista as pv

        faces = []
        for face in self.faces:
            faces.append(len(face))
            faces.extend(face)
        return pv.PolyData(self.vertices, faces=np.asarray(faces))


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------
def _points_of(geometry: Any) -> np.ndarray:
    """Return an ``(N, 3)`` point array from a Solid / array / shapely polygon."""
    if isinstance(geometry, Solid):
        return geometry.vertices
    if isinstance(geometry, Polygon):
        return _polygon_to_3d(geometry)
    if isinstance(geometry, (MultiPolygon,)):
        return np.vstack([_polygon_to_3d(p) for p in geometry.geoms])
    arr = np.asarray(geometry, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.shape[1] == 2:  # pad 2D -> 3D at z=0
        arr = np.hstack([arr, np.zeros((len(arr), 1))])
    return arr


def _polygon_to_3d(poly: Polygon, z: float = 0.0) -> np.ndarray:
    coords = np.asarray(poly.exterior.coords[:-1], dtype=float)
    return np.hstack([coords, np.full((len(coords), 1), z)])


def _faces_as_2d(geometry: Any, plane: str) -> List[Polygon]:
    """Project each face of a Solid onto ``plane`` and return 2D polygons."""
    i, j = PLANE_AXES[plane]
    polys: List[Polygon] = []
    if isinstance(geometry, Solid) and geometry.faces:
        for face in geometry.faces:
            pts = geometry.face_coords(face)[:, [i, j]]
            if len(pts) >= 3:
                p = Polygon(pts)
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty and p.area > 0:
                    polys.append(p)
    else:
        pts = _points_of(geometry)[:, [i, j]]
        if len(pts) >= 3:
            hull = Polygon(pts).convex_hull
            if isinstance(hull, Polygon) and not hull.is_empty:
                polys.append(hull)
    return polys


# ---------------------------------------------------------------------------
# Operators (ISO 19166 Table 8)
# ---------------------------------------------------------------------------
def projection(geometry: Any, plane: str = "XY") -> BaseGeometry:
    """Project a 3D geometry onto a reference plane, returning a 2D area."""
    if plane not in PLANE_AXES:
        raise ValueError(f"plane must be one of {sorted(PLANE_AXES)}, got {plane!r}")
    polys = _faces_as_2d(_geometry_of(geometry), plane)
    if not polys:
        return Polygon()
    merged = unary_union(polys)
    return merged


def boundary(geometry: Any, plane: str = "XY") -> BaseGeometry:
    """Return the 2D outline (boundary edges) of a geometry on a plane."""
    area = projection(geometry, plane)
    if area.is_empty:
        return LineString()
    return area.boundary


def footprint(element: Any) -> BaseGeometry:
    """Return the 2D footprint (projection onto the XY/ground plane)."""
    return projection(_geometry_of(element), "XY")


def obb(geometry: Any) -> OBB:
    """Compute an oriented bounding box via principal component analysis."""
    pts = _points_of(_geometry_of(geometry))
    center = pts.mean(axis=0)
    centered = pts - center
    # principal axes from the covariance matrix
    cov = np.cov(centered.T) if len(pts) > 1 else np.eye(3)
    _, axes = np.linalg.eigh(cov)
    axes = axes.T[::-1]  # largest variance first
    # extent along each principal axis
    projected = centered @ axes.T
    mins, maxs = projected.min(axis=0), projected.max(axis=0)
    extent = maxs - mins
    # recentre using the mid-point of the projected extents
    mid = (maxs + mins) / 2.0
    center = center + mid @ axes
    return OBB(
        center=tuple(center),
        x_direction=tuple(axes[0]),
        y_direction=tuple(axes[1]),
        z_direction=tuple(axes[2]),
        extent=tuple(extent),
    )


def extrude(
    geometry2d: Union[Polygon, BaseGeometry],
    v: Union[Vector3D, Sequence[float]] = (0.0, 0.0, 1.0),
    height: float = 1.0,
    base_z: float = 0.0,
) -> Solid:
    """Extrude a 2D polygon along direction ``v`` by ``height`` into a Solid.

    Implements ``extrude(g: geometry2D, v: vector3D, height: real): geometry``.
    Interior rings (holes) are ignored for the LOD block model.
    """
    if isinstance(geometry2d, MultiPolygon):
        # extrude each part and merge into a single solid
        solids = [extrude(p, v, height, base_z) for p in geometry2d.geoms]
        return _merge_solids(solids)
    if not isinstance(geometry2d, Polygon) or geometry2d.is_empty:
        raise ValueError("extrude() requires a non-empty 2D Polygon")

    direction = v.as_array() if isinstance(v, Vector3D) else np.asarray(v, dtype=float)
    norm = np.linalg.norm(direction)
    if norm == 0:
        raise ValueError("extrude() direction vector must be non-zero")
    offset = direction / norm * float(height)

    ring = np.asarray(geometry2d.exterior.coords[:-1], dtype=float)  # drop closing dup
    n = len(ring)
    if n < 3:
        raise ValueError("extrude() polygon must have at least 3 vertices")

    bottom = np.hstack([ring, np.full((n, 1), base_z)])
    top = bottom + offset
    vertices = np.vstack([bottom, top])

    faces: List[List[int]] = []
    faces.append(list(range(n - 1, -1, -1)))          # bottom (downward normal)
    faces.append(list(range(n, 2 * n)))               # top (upward normal)
    for i in range(n):                                # side quads
        a, b = i, (i + 1) % n
        faces.append([a, b, b + n, a + n])
    return Solid(vertices, faces)


def exterior(geometry: Any) -> Solid:
    """Return the outer shell of a solid.

    For a single-shell solid this is the solid itself; for meshes composed of
    several disconnected shells the outermost (largest bounding volume) shell is
    returned.
    """
    solid = _as_solid(geometry)
    shells = _split_shells(solid)
    if len(shells) <= 1:
        return solid
    return max(shells, key=lambda s: np.prod(s.bounds()[1] - s.bounds()[0]))


def interior(geometry: Any) -> Solid:
    """Return the inner shells of a solid (everything but the outer shell).

    Returns an empty Solid when the geometry has a single shell.
    """
    solid = _as_solid(geometry)
    shells = _split_shells(solid)
    if len(shells) <= 1:
        return Solid(np.zeros((0, 3)), [])
    # the outer shell is the one with the largest bounding-box volume
    sizes = [float(np.prod(s.bounds()[1] - s.bounds()[0])) for s in shells]
    outer_idx = int(np.argmax(sizes))
    inners = [s for i, s in enumerate(shells) if i != outer_idx]
    return _merge_solids(inners) if inners else Solid(np.zeros((0, 3)), [])


def void(element: Any) -> List[Any]:
    """Return the VOID-type sub-elements (windows, doors, openings) of ``element``.

    ``element`` may be a BIM object dict with a ``children``/``related_objects``
    list, or an iterable of such objects.
    """
    def is_void(obj: Any) -> bool:
        t = obj.get("ifc_type") if isinstance(obj, dict) else getattr(obj, "ifc_type", "")
        return t in VOID_ELEMENT_TYPES

    if isinstance(element, dict):
        children = element.get("children") or element.get("related_objects") or []
        result = [c for c in children if is_void(c)]
        if is_void(element):
            result.append(element)
        return result
    if isinstance(element, Iterable):
        return [o for o in element if is_void(o)]
    return []


# --- boolean set operators (Table 8: union / subtract / intersect) ---------
_SHAPELY_OPS = {"union": "union", "subtract": "difference", "intersect": "intersection"}


def _prism_of(solid: Solid, tol: float = 1e-6) -> Optional[Tuple[Polygon, float, float]]:
    """Return ``(footprint, z_min, z_max)`` when ``solid`` is a vertical prism."""
    if len(solid.vertices) < 6 or not solid.faces:
        return None
    z = solid.vertices[:, 2]
    lo, hi = float(z.min()), float(z.max())
    if hi - lo <= tol:
        return None
    if not np.all((np.abs(z - lo) < tol) | (np.abs(z - hi) < tol)):
        return None
    bottom = projection(solid, "XY")
    if bottom.is_empty or not isinstance(bottom, (Polygon, MultiPolygon)):
        return None
    return bottom, lo, hi


def _prism_boolean(s1: Solid, s2: Solid, op: str) -> Solid:
    """Boolean on two vertical prisms, done on the footprint and re-extruded."""
    p1, p2 = _prism_of(s1), _prism_of(s2)
    if p1 is None or p2 is None:
        raise NotImplementedError(
            "3D boolean needs a mesh backend (pip install manifold3d) "
            "or two vertical prisms"
        )
    (f1, lo1, hi1), (f2, lo2, hi2) = p1, p2
    if op == "intersect":
        lo, hi = max(lo1, lo2), min(hi1, hi2)
        if hi - lo <= 0:
            return Solid(np.zeros((0, 3)), [])
    elif op == "union":
        # only exact z-alignment keeps the result a prism
        if abs(lo1 - lo2) > 1e-6 or abs(hi1 - hi2) > 1e-6:
            raise NotImplementedError("prism union needs both solids on the same z range")
        lo, hi = lo1, hi1
    else:  # subtract
        if lo2 > lo1 + 1e-6 or hi2 < hi1 - 1e-6:
            raise NotImplementedError("prism subtract needs the cutter to span the target z range")
        lo, hi = lo1, hi1
    area = getattr(f1, _SHAPELY_OPS[op])(f2)
    if area.is_empty:
        return Solid(np.zeros((0, 3)), [])
    return extrude(area, (0.0, 0.0, 1.0), hi - lo, base_z=lo)


def _as_manifold(solid: Solid):
    """Wrap a Solid as a manifold3d.Manifold.

    Mesh64 rather than Mesh: after the CM stage the coordinates are in the
    destination CRS, and float32 resolves to about a metre at that magnitude,
    which erases building detail entirely.
    """
    import manifold3d

    mesh = _triangulated(solid)
    return manifold3d.Manifold(manifold3d.Mesh64(
        vert_properties=np.asarray(mesh["vertices"], dtype=np.float64),
        tri_verts=np.asarray(mesh["faces"], dtype=np.uint32),
    ))


def _mesh_boolean(s1: Solid, s2: Solid, op: str) -> Optional[Solid]:
    """Mesh boolean through manifold3d when it is installed."""
    try:
        import manifold3d  # noqa: F401
    except Exception:
        return None
    try:
        a, b = _as_manifold(s1), _as_manifold(s2)
        result = {"union": a + b, "subtract": a - b, "intersect": a ^ b}[op]
        if result.is_empty():
            return Solid(np.zeros((0, 3)), [])
        mesh = result.to_mesh64()
    except Exception:
        return None
    vertices = np.asarray(mesh.vert_properties, dtype=float)[:, :3]
    faces = [list(map(int, tri)) for tri in np.asarray(mesh.tri_verts)]
    if not faces:
        return Solid(np.zeros((0, 3)), [])
    return Solid(vertices, faces)


def _boolean(g1: Any, g2: Any, op: str) -> Any:
    if isinstance(g1, BaseGeometry) and isinstance(g2, BaseGeometry):
        return getattr(g1, _SHAPELY_OPS[op])(g2)
    a, b = _geometry_of(g1), _geometry_of(g2)
    if isinstance(a, BaseGeometry) and isinstance(b, BaseGeometry):
        return getattr(a, _SHAPELY_OPS[op])(b)
    s1, s2 = _as_solid(a), _as_solid(b)
    meshed = _mesh_boolean(s1, s2, op)
    return meshed if meshed is not None else _prism_boolean(s1, s2, op)


def union(g1: Any, g2: Any) -> Any:
    return _boolean(g1, g2, "union")


def subtract(g1: Any, g2: Any) -> Any:
    return _boolean(g1, g2, "subtract")


def intersect(g1: Any, g2: Any) -> Any:
    return _boolean(g1, g2, "intersect")


# ---------------------------------------------------------------------------
# High-level LOD generation (rule-driven, no hard-coded cases)
# ---------------------------------------------------------------------------
def generate_lod1(element: Any, height: float, base_z: float = 0.0) -> Solid:
    """LOD1 block model: extrude the footprint straight up by ``height``."""
    fp = footprint(element)
    if fp.is_empty:
        raise ValueError("cannot build LOD1: geometry has no footprint")
    return extrude(fp, Vector3D((0.0, 0.0, 1.0)), height, base_z=base_z)


# operator registry so a rule set can reference operators declaratively
OPERATORS = {
    "footprint": footprint,
    "OBB": obb,
    "obb": obb,
    "projection": projection,
    "boundary": boundary,
    "extrude": extrude,
    "exterior": exterior,
    "interior": interior,
    "VOID": void,
    "void": void,
    "union": union,
    "subtract": subtract,
    "intersect": intersect,
}


def apply_operator(name: str, *args, **kwargs):
    """Invoke a named B2G LM operator (used by declarative rule sets)."""
    if name not in OPERATORS:
        raise KeyError(f"unknown LM operator: {name!r}; known: {sorted(OPERATORS)}")
    return OPERATORS[name](*args, **kwargs)


# ---------------------------------------------------------------------------
# Declarative operator chains (pipeline / CLI driven)
# ---------------------------------------------------------------------------
def _triangulated(solid: Solid) -> Dict[str, Any]:
    """Fan-triangulate every face; returns kwargs for a triangle mesh."""
    tris: List[List[int]] = []
    for face in solid.faces:
        for i in range(1, len(face) - 1):
            tris.append([face[0], face[i], face[i + 1]])
    return {"vertices": solid.vertices, "faces": np.asarray(tris, dtype=int).reshape(-1, 3)}


def to_brep(geometry: Any, z: float = 0.0) -> Optional[Dict[str, List[float]]]:
    """Convert an operator result to the flat ``{'verts', 'faces'}`` B-rep."""
    if geometry is None:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        parts = geometry.geoms if isinstance(geometry, MultiPolygon) else [geometry]
        solid = _merge_solids([_flat_face(p, z) for p in parts if not p.is_empty])
    elif isinstance(geometry, Solid):
        solid = geometry
    elif isinstance(geometry, OBB):
        solid = _obb_solid(geometry)
    else:
        return None
    if len(solid.vertices) == 0 or not solid.faces:
        return None
    mesh = _triangulated(solid)
    return {
        "verts": [float(c) for c in np.asarray(mesh["vertices"]).reshape(-1)],
        "faces": [int(i) for i in np.asarray(mesh["faces"]).reshape(-1)],
    }


def _flat_face(poly: Polygon, z: float) -> Solid:
    ring = np.asarray(poly.exterior.coords[:-1], dtype=float)
    verts = np.hstack([ring, np.full((len(ring), 1), z)])
    return Solid(verts, [list(range(len(ring)))])


def _obb_solid(box: OBB) -> Solid:
    x = np.asarray(box.x_direction, dtype=float)
    y = np.asarray(box.y_direction, dtype=float)
    zdir = np.asarray(box.z_direction, dtype=float)
    ex, ey, ez = box.extent
    centre = np.asarray(box.center, dtype=float)
    corners = []
    for sx in (-0.5, 0.5):
        for sy in (-0.5, 0.5):
            for sz in (-0.5, 0.5):
                corners.append(centre + x * (sx * ex) + y * (sy * ey) + zdir * (sz * ez))
    faces = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
    return Solid(np.asarray(corners), faces)


def run_chain(source: Any, steps: Any, resolver=None) -> Any:
    """Run a declarative operator chain and return the final geometry.

    ``steps`` is a list of ``{"op": name, "args": {...}}`` (a bare string or a
    single dict is accepted too).  The first step gets ``source``; each later
    step gets the previous result as its first argument.  ``resolver`` maps an
    argument value to a concrete one, letting a rule reference element data.
    """
    result = source
    for index, step in enumerate(_normalise_steps(steps)):
        name = step["op"]
        args = dict(step.get("args") or {})
        if resolver is not None:
            args = {k: resolver(v) for k, v in args.items()}
        positional = args.pop("_args", [])
        if step.get("source") == "element" or index == 0:
            result = apply_operator(name, source if index == 0 else result, *positional, **args)
        else:
            result = apply_operator(name, result, *positional, **args)
    return result


def _normalise_steps(steps: Any) -> List[Dict[str, Any]]:
    if steps is None:
        return []
    if isinstance(steps, str):
        return [{"op": steps}]
    if isinstance(steps, dict):
        steps = [steps]
    out = []
    for step in steps:
        if isinstance(step, str):
            out.append({"op": step})
        elif isinstance(step, dict):
            name = step.get("op") or step.get("name")
            if not name:
                raise ValueError(f"operator step needs an 'op' name: {step!r}")
            out.append({**step, "op": name})
        else:
            raise ValueError(f"unsupported operator step: {step!r}")
    return out


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------
def from_brep(brep: Dict[str, Any]) -> Solid:
    """Build a Solid from the flat ``{'verts': [...], 'faces': [...]}`` B-rep
    produced by the BIM parser (faces are consecutive triangle indices)."""
    flat_v = list(brep.get("verts") or [])
    flat_f = list(brep.get("faces") or [])
    verts = np.asarray(flat_v, dtype=float).reshape(-1, 3) if flat_v else np.zeros((0, 3))
    faces = [list(map(int, flat_f[i:i + 3])) for i in range(0, len(flat_f) - 2, 3)]
    return Solid(verts, faces)


def _geometry_of(element: Any) -> Any:
    """Extract a geometry from a BIM object dict, or pass geometry through."""
    if isinstance(element, dict):
        if "verts" in element:            # flat B-rep straight from the BIM parser
            return from_brep(element)
        geom = element.get("solid") or element.get("geometry") or element.get("geometries")
        if isinstance(geom, list) and geom:
            geom = geom[0]
        if isinstance(geom, dict) and "verts" in geom:
            return from_brep(geom)
        if geom is not None:
            return geom
    return element


def _as_solid(geometry: Any) -> Solid:
    geometry = _geometry_of(geometry)
    if isinstance(geometry, Solid):
        return geometry
    pts = _points_of(geometry)
    return Solid(pts, [])


def _merge_solids(solids: Sequence[Solid]) -> Solid:
    verts: List[np.ndarray] = []
    faces: List[List[int]] = []
    offset = 0
    for s in solids:
        if len(s.vertices) == 0:
            continue
        verts.append(s.vertices)
        faces.extend([[i + offset for i in f] for f in s.faces])
        offset += len(s.vertices)
    if not verts:
        return Solid(np.zeros((0, 3)), [])
    return Solid(np.vstack(verts), faces)


def _split_shells(solid: Solid) -> List[Solid]:
    """Split a solid into connected components (shells) via face adjacency."""
    if not solid.faces:
        return [solid]
    n = len(solid.faces)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def unite(a: int, b: int):
        parent[find(a)] = find(b)

    # union faces that share a vertex index
    vertex_to_faces: Dict[int, List[int]] = {}
    for fi, face in enumerate(solid.faces):
        for vi in face:
            vertex_to_faces.setdefault(vi, []).append(fi)
    for faces_here in vertex_to_faces.values():
        for k in range(1, len(faces_here)):
            unite(faces_here[0], faces_here[k])

    groups: Dict[int, List[int]] = {}
    for fi in range(n):
        groups.setdefault(find(fi), []).append(fi)
    if len(groups) <= 1:
        return [solid]

    shells: List[Solid] = []
    for face_ids in groups.values():
        used = sorted({vi for fi in face_ids for vi in solid.faces[fi]})
        remap = {vi: i for i, vi in enumerate(used)}
        verts = solid.vertices[used]
        faces = [[remap[vi] for vi in solid.faces[fi]] for fi in face_ids]
        shells.append(Solid(verts, faces))
    return shells


if __name__ == "__main__":
    square = Polygon([(0, 0), (10, 0), (10, 20), (0, 20)])
    block = extrude(square, Vector3D((0, 0, 1)), height=12.0)
    print("LOD1 block volume:", block.volume(), "(expected 2400)")
    print("footprint area:", footprint(block).area, "(expected 200)")
    box = obb(block)
    print("OBB extent:", [round(e, 2) for e in box.extent])
