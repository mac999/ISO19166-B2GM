"""
B2GM LM - LoD Mapping (ISO 19166 B2GM, stage 3).

LoD Mapping ("B2G LM" in ``doc/fig1.JPG``) assigns a GIS Level-of-Detail
(LOD0..LOD4) to each mapped element.  A pipeline LM stage looks like::

    {
      "type": "LM",
      "rule": [ {"source": "IfcBuilding", "lod": "LOD1"} ]
    }

When no rule matches an element, a configurable default LoD is used.  The
heavier geometric LoD generation (footprint extrusion) lives in
``B2GM_LM_op_extrude.py``.

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
    """A rule that assigns a LoD name to elements matching ``source`` (``LM_rule``).

    ISO 19166 Table 8 ``LM_rule`` carries a ``name``; this implementation adds the
    functional ``source`` (regex) and ``lod`` (target LoD) fields used to drive
    the mapping.
    """

    def __init__(self, source: str = ".*", lod: str = DEFAULT_LOD, name: str = ""):
        self.source = source
        self.lod = lod
        self.name = name or f"{source}->{lod}"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LoDRule":
        lod = d.get("lod") or d.get("destination") or DEFAULT_LOD
        return cls(d.get("source", ".*"), lod, d.get("name", ""))

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "source": self.source, "lod": self.lod}

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


def assign_lod(
    objects: List[Dict[str, Any]],
    rules: List[LoDRule],
    default_lod: str = DEFAULT_LOD,
) -> List[Dict[str, Any]]:
    """Return objects annotated with an ``_lod`` key (in place-safe copies)."""
    out: List[Dict[str, Any]] = []
    for obj in objects:
        lod: Optional[str] = None
        for rule in rules:
            if rule.matches(obj):
                lod = rule.lod
                break
        tagged = dict(obj)
        tagged["_lod"] = lod or default_lod
        out.append(tagged)
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

    B2GM_GIS.GIS().store(args.output, objects, stage)
    logging.info("Wrote %s", args.output)


if __name__ == "__main__":
    main()
