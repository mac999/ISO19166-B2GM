"""
B2GM EM - Element Mapping (ISO 19166 B2GM, stage 2).

Element Mapping ("B2G EM" in ``doc/fig1.JPG``) maps a BIM/IFC element to its
GIS/CityGML counterpart using a set of rules::

    { "source": "IfcBuilding", "destination": "CityModel.Building", "child_node": ".*" }

Usage (stand-alone):
    python B2GM_element.py --input model.ifc --output city.gml --option rules.json

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


# EM_rule.PSet_operation values (ISO 19166 Table 5)
PSET_REPLACE = "Replace"
PSET_APPEND = "Append"


class ElementRule:
    """A single source(IFC) -> destination(GIS) element mapping rule.

    ``pset_operation`` follows ISO 19166 Table 5 ``EM_rule.PSet_operation``:

    * ``Append``  - the source property sets are added to the destination
      (default);
    * ``Replace`` - the destination property sets are replaced by the source.
    """

    def __init__(
        self,
        source: str,
        destination: str,
        child_node: str = ".*",
        pset_operation: str = PSET_APPEND,
    ):
        self.source = source
        self.destination = destination
        self.child_node = child_node
        self.pset_operation = pset_operation

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ElementRule":
        return cls(
            d.get("source", ""),
            d.get("destination", ""),
            d.get("child_node", ".*"),
            d.get("PSet_operation", d.get("pset_operation", PSET_APPEND)),
        )

    def matches(self, obj: Dict[str, Any]) -> bool:
        """Match the rule source against an object's IFC type / name / code.

        The ``source`` is a full-match regular expression (use ``.*Wall.*`` for
        substring matching), so ``IfcBuilding`` does not match ``IfcBuildingStorey``.

        When the element carries an IFC ``PredefinedType`` (e.g. an ``IfcSlab``
        with ``ROOF``), a compound candidate ``"<ifc_type>.<PredefinedType>"``
        (e.g. ``"IfcSlab.ROOF"``) is also matched, so a rule can refine a type by
        its predefined kind while a plain ``"IfcSlab"`` rule still matches every
        slab.
        """
        ifc_type = obj.get("ifc_type", "")
        predefined = obj.get("predefined_type", "")
        candidates = [
            ifc_type,
            f"{ifc_type}.{predefined}" if ifc_type and predefined else "",
            obj.get("name", ""),
            obj.get("code", ""),
        ]
        return any(c and re.fullmatch(self.source, str(c)) for c in candidates)


def rules_from_stage(stage: Dict[str, Any]) -> List[ElementRule]:
    return [ElementRule.from_dict(r) for r in stage.get("rule", [])]


def map_rule(obj: Dict[str, Any], rules: List[ElementRule]) -> Optional[ElementRule]:
    """Return the first rule matching ``obj`` (or ``None``)."""
    for rule in rules:
        if rule.matches(obj):
            return rule
    return None


def map_element(obj: Dict[str, Any], rules: List[ElementRule]) -> Optional[str]:
    """Return the destination GIS element name for ``obj`` or ``None``."""
    rule = map_rule(obj, rules)
    return rule.destination if rule else None


def merge_psets(
    dest_psets: Dict[str, Any], src_psets: Dict[str, Any], operation: str = PSET_APPEND
) -> Dict[str, Any]:
    """Combine two ``{pset_name: {prop: value}}`` maps per ``PSet_operation``.

    ``Replace`` returns the source unchanged; ``Append`` merges the source into a
    copy of the destination (source values win on key collisions).
    """
    if operation == PSET_REPLACE:
        return dict(src_psets or {})
    merged = {name: dict(props) for name, props in (dest_psets or {}).items()}
    for name, props in (src_psets or {}).items():
        merged.setdefault(name, {}).update(props or {})
    return merged


def apply(objects: List[Dict[str, Any]], rules: List[ElementRule]) -> List[Dict[str, Any]]:
    """Return the subset of objects that match a rule, tagged for downstream stages.

    Each returned dict is a shallow copy with ``_destination`` (the GIS target
    class) and ``_pset_operation`` (Table 5 ``PSet_operation``) added, so LoD
    mapping and serialisation know how to treat the element.
    """
    mapped: List[Dict[str, Any]] = []
    for obj in objects:
        rule = map_rule(obj, rules)
        if rule is None:
            continue
        tagged = dict(obj)
        tagged["_destination"] = rule.destination
        tagged["_pset_operation"] = rule.pset_operation
        mapped.append(tagged)
    return mapped


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="B2GM element (EM) mapping")
    parser.add_argument("--input", required=True, help="Input IFC file")
    parser.add_argument("--output", required=True, help="Output CityGML file")
    parser.add_argument("--option", required=True, help="Rule option JSON file")
    args = parser.parse_args()

    import B2GM_BIM
    import B2GM_GIS

    with open(args.option, "r", encoding="utf-8") as f:
        stage = json.load(f)
    # allow either a bare stage dict or a pipeline file
    if "BIM_GIS_mapping.pipeline" in stage:
        stage = next(s for s in stage["BIM_GIS_mapping.pipeline"] if s.get("type") == "EM")

    rules = rules_from_stage(stage)
    objects = B2GM_BIM.BIM().parse(args.input)
    mapped = apply(objects, rules)
    logging.info("EM mapped %d / %d elements", len(mapped), len(objects))

    B2GM_GIS.GIS().store(args.output, objects, stage)
    logging.info("Wrote %s", args.output)


if __name__ == "__main__":
    main()
