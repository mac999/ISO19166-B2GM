"""
B2GM LM - LoD Mapping (ISO 19166 B2GM, stage 3).

LoD Mapping ("B2G LM" in ``doc/fig1.JPG``) assigns a GIS Level-of-Detail
(LOD0..LOD4) to each mapped element and, optionally, rebuilds its geometry with
the ISO 19166 Table 8 operators.  A pipeline LM stage looks like::

    {
      "type": "LM",
      "rule": [
        {"source": "IfcBuilding", "lod": "LOD1",
         "operation": [{"op": "footprint"},
                       {"op": "extrude", "args": {"height": {"$extent": "z"}}}]}
      ]
    }

The operation chain runs in ``B2GM_LM_operators`` and its result replaces the
element geometry (``_lod_geometry``).  Argument values may reference the element
itself: ``{"$property": "Pset.Name"}``, ``{"$extent": "z"}``, ``{"$min": "z"}``,
``{"$max": "z"}``.  When no rule matches, a configurable default LoD is used.

Usage (stand-alone):
    python B2GM_LM.py --input city.gml --output city_LoD.gml --option rules.json

Author:
    Taewook Kang (laputa99999@gmail.com)

Date:
    2024-01-02 (completed 2026-07)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from typing import Any, Dict, List, Optional

DEFAULT_LOD = "LOD1"


class LoDRule:
    """Assigns a LoD (and optionally new geometry) to matching elements.

    ISO 19166 ``LM_rule`` carries a ``name``; ``source`` (regex), ``lod`` and
    ``operation`` (a Table 8 operator chain) drive the mapping.  ``aggregate`` is
    a regex over IFC types: when set the chain runs on the merged geometry of
    every matching element instead of the matched element's own (an IfcBuilding
    carries no geometry of its own, so its LOD1 block comes from its parts).
    """

    def __init__(self, source: str = ".*", lod: str = DEFAULT_LOD, name: str = "",
                 operation: Any = None, aggregate: str = ""):
        self.source = source
        self.lod = lod
        self.operation = operation
        self.aggregate = aggregate
        self.name = name or f"{source}->{lod}"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LoDRule":
        lod = d.get("lod") or d.get("destination") or DEFAULT_LOD
        return cls(d.get("source", ".*"), lod, d.get("name", ""), d.get("operation"),
                   d.get("aggregate", ""))

    def to_dict(self) -> Dict[str, Any]:
        out = {"name": self.name, "source": self.source, "lod": self.lod}
        if self.operation:
            out["operation"] = self.operation
        if self.aggregate:
            out["aggregate"] = self.aggregate
        return out

    def matches(self, obj: Dict[str, Any]) -> bool:
        # source is a full-match regex, consistent with element (EM) mapping;
        # a compound "<ifc_type>.<PredefinedType>" candidate lets a LoD rule
        # refine by predefined kind (e.g. "IfcSlab.ROOF").
        ifc_type = obj.get("ifc_type", "")
        predefined = obj.get("predefined_type", "")
        candidates = [
            ifc_type,
            f"{ifc_type}.{predefined}" if ifc_type and predefined else "",
            obj.get("name", ""),
            obj.get("code", ""),
        ]
        return any(c and re.fullmatch(self.source, str(c)) for c in candidates)

    def run_operation(self, obj: Dict[str, Any], model: Optional[List[Dict[str, Any]]] = None):
        """Run the rule's operator chain against ``obj``; returns a B-rep or None."""
        if not self.operation:
            return None
        import B2GM_LM_operators as OP

        source = obj
        if self.aggregate:
            merged = aggregate_geometry(model or [], self.aggregate)
            if not merged:
                raise ValueError(f"aggregate {self.aggregate!r} matched no geometry")
            source = {**obj, "geometry": merged}
        result = OP.run_chain(source, self.operation, resolver=lambda v: resolve_arg(v, source))
        # a 2D result (footprint, projection, boolean) carries no elevation, so it
        # stays at the element's own base rather than dropping to z = 0
        bounds = element_bounds(source)
        return OP.to_brep(result, z=bounds[0][2] if bounds else 0.0)


class LM_ruleset:  # noqa: N801 - ISO 19166 Table 8 LM_ruleset complexType
    """A named set of LoD-mapping rules (ISO 19166 ``LM_ruleset`` = ``{name,
    LM_rule(0..*)}``)."""

    def __init__(self, name: str = "", rules: Optional[List[LoDRule]] = None):
        self.name = name
        self.rules: List[LoDRule] = rules if rules is not None else []

    @classmethod
    def from_stage(cls, stage: Dict[str, Any]) -> "LM_ruleset":
        return cls(stage.get("name", ""), rules_from_stage(stage))

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "LM_rule": [r.to_dict() for r in self.rules]}


def rules_from_stage(stage: Dict[str, Any]) -> List[LoDRule]:
    return [LoDRule.from_dict(r) for r in stage.get("rule", [])]


def ruleset_from_stage(stage: Dict[str, Any]) -> LM_ruleset:
    """Build the ISO 19166 ``LM_ruleset`` object for a pipeline LM stage."""
    return LM_ruleset.from_stage(stage)


_AXIS = {"x": 0, "y": 1, "z": 2}


def element_bounds(obj: Dict[str, Any]):
    """Return ``(min_xyz, max_xyz)`` of an element's B-rep, or ``None``."""
    verts = (obj.get("geometry") or {}).get("verts") or []
    if len(verts) < 3:
        return None
    lo = [min(verts[i::3]) for i in range(3)]
    hi = [max(verts[i::3]) for i in range(3)]
    return lo, hi


def aggregate_geometry(objects: List[Dict[str, Any]], pattern: str) -> Optional[Dict[str, Any]]:
    """Merge the B-reps of every element whose IFC type matches ``pattern``."""
    verts: List[float] = []
    faces: List[int] = []
    for obj in objects:
        if not re.fullmatch(pattern, str(obj.get("ifc_type", ""))):
            continue
        geom = obj.get("geometry") or {}
        v, f = geom.get("verts") or [], geom.get("faces") or []
        if not v or not f:
            continue
        offset = len(verts) // 3
        verts.extend(float(c) for c in v)
        faces.extend(int(i) + offset for i in f)
    return {"verts": verts, "faces": faces} if faces else None


def _lookup_property(obj: Dict[str, Any], path: str):
    """Look up ``"Pset.Property"`` (or a bare property name) in an element."""
    psets = obj.get("pset") or {}
    if "." in path:
        pset_name, prop = path.split(".", 1)
        return (psets.get(pset_name) or {}).get(prop)
    for props in psets.values():
        if path in (props or {}):
            return props[path]
    return obj.get(path)


def resolve_arg(value: Any, obj: Dict[str, Any]) -> Any:
    """Resolve an operator argument that references the element."""
    if not isinstance(value, dict) or len(value) != 1:
        return value
    key, arg = next(iter(value.items()))
    if key == "$property":
        found = _lookup_property(obj, str(arg))
        try:
            return float(found)
        except (TypeError, ValueError):
            return found
    if key in ("$extent", "$min", "$max"):
        bounds = element_bounds(obj)
        if bounds is None:
            raise ValueError(f"{key} needs element geometry")
        lo, hi = bounds
        axis = _AXIS[str(arg).lower()]
        return hi[axis] - lo[axis] if key == "$extent" else (lo if key == "$min" else hi)[axis]
    return value


def assign_lod(
    objects: List[Dict[str, Any]],
    rules: List[LoDRule],
    default_lod: str = DEFAULT_LOD,
) -> List[Dict[str, Any]]:
    """Annotate objects with ``_lod`` and, when a rule has an operator chain,
    the geometry it produces (``_lod_geometry``)."""
    out: List[Dict[str, Any]] = []
    applied = 0
    for obj in objects:
        matched: Optional[LoDRule] = next((r for r in rules if r.matches(obj)), None)
        tagged = dict(obj)
        tagged["_lod"] = (matched.lod if matched else None) or default_lod
        if matched is not None and matched.operation:
            try:
                brep = matched.run_operation(obj, objects)
            except Exception as exc:
                logging.warning("LM operator %s failed on %s: %s",
                                matched.name, obj.get("name", "?"), exc)
                brep = None
            if brep:
                tagged["_lod_geometry"] = brep
                tagged["_lod_operation"] = matched.operation
                applied += 1
        out.append(tagged)
    if applied:
        logging.info("LM operators rebuilt geometry for %d elements", applied)
    return out


def lod1_from_footprint(footprint, height, base_z: float = 0.0):
    """Generate a LOD1 block solid from a footprint using the B2G LM operators.

    ``footprint`` may be a shapely Polygon or anything the operators accept.
    Delegates to :func:`B2GM_LM_operators.extrude` (numpy + shapely only), so no
    heavy 3D dependency is required. Returns a :class:`B2GM_LM_operators.Solid`.
    """
    import B2GM_LM_operators as OP

    return OP.extrude(footprint, (0.0, 0.0, 1.0), float(height), base_z=base_z)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="B2GM LoD (LM) mapping")
    parser.add_argument("--input", required=True, help="Input IFC or CityGML file")
    parser.add_argument("--output", required=True, help="Output CityGML file")
    parser.add_argument("--option", required=True, help="Rule option JSON file")
    parser.add_argument("--citygml-version", dest="citygml_version",
                        choices=["2.0", "3.0"], default=None,
                        help="CityGML output version (default: 2.0)")
    args = parser.parse_args()

    import B2GM_BIM
    import B2GM_GIS

    with open(args.option, "r", encoding="utf-8") as f:
        stage = json.load(f)
    if "BIM_GIS_mapping.pipeline" in stage:
        stage = next(s for s in stage["BIM_GIS_mapping.pipeline"] if s.get("type") == "LM")

    rules = rules_from_stage(stage)
    objects = B2GM_BIM.BIM().parse(args.input)
    objects = assign_lod(objects, rules)
    logging.info("LM assigned LoD to %d elements", len(objects))

    version = B2GM_GIS.version_from_stage(stage, args.citygml_version)
    B2GM_GIS.GIS().store(args.output, objects, stage, version=version)
    logging.info("Wrote %s", args.output)


if __name__ == "__main__":
    main()
