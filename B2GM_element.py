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


class EM_source:  # noqa: N801 - ISO 19166 EM_source complexType
    """Source element name of an EM rule (``EM_source.element``)."""

    def __init__(self, element: str = ""):
        self.element = element

    def to_dict(self) -> Dict[str, Any]:
        return {"element": self.element}


class EM_destination:  # noqa: N801 - ISO 19166 EM_destination complexType
    """Destination element name of an EM rule (``EM_destination.element``)."""

    def __init__(self, element: str = ""):
        self.element = element

    def to_dict(self) -> Dict[str, Any]:
        return {"element": self.element}


class ElementRule:
    """A single source(IFC) -> destination(GIS) element mapping rule (``EM_rule``).

    Mirrors ISO 19166 Table 6 ``EM_rule`` = ``{name, destination, PSet_operation,
    EM_source, EM_destination}``.  ``source``/``destination`` remain the primary
    (regex) matching fields; ``em_source``/``em_destination`` expose the same
    values as the schema's wrapper objects.

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
        name: str = "",
    ):
        self.name = name or f"{source}->{destination}"
        self.source = source
        self.destination = destination
        self.child_node = child_node
        self.pset_operation = pset_operation
        # XSD EM_rule -> EM_source / EM_destination wrappers
        self.em_source = EM_source(source)
        self.em_destination = EM_destination(destination)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ElementRule":
        return cls(
            d.get("source", ""),
            d.get("destination", ""),
            d.get("child_node", ".*"),
            d.get("PSet_operation", d.get("pset_operation", PSET_APPEND)),
            d.get("name", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "destination": self.destination,
            "PSet_operation": self.pset_operation,
            "EM_source": self.em_source.to_dict(),
            "EM_destination": self.em_destination.to_dict(),
        }

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


class EM_ruleset:  # noqa: N801 - ISO 19166 EM_ruleset complexType
    """A named set of EM rules (ISO 19166 Table 6 ``EM_ruleset``).

    Members: ``{name, description, BIM_model_source, GIS_model_destination,
    EM_rule(0..*)}``.
    """

    def __init__(
        self,
        name: str = "",
        description: str = "",
        bim_model_source: str = "",
        gis_model_destination: str = "",
        rules: Optional[List[ElementRule]] = None,
    ):
        self.name = name
        self.description = description
        self.bim_model_source = bim_model_source
        self.gis_model_destination = gis_model_destination
        self.rules: List[ElementRule] = rules if rules is not None else []

    @classmethod
    def from_stage(cls, stage: Dict[str, Any]) -> "EM_ruleset":
        return cls(
            stage.get("name", ""),
            stage.get("description", ""),
            stage.get("BIM_model_source", stage.get("input", "")),
            stage.get("GIS_model_destination", stage.get("output", "")),
            rules_from_stage(stage),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "BIM_model_source": self.bim_model_source,
            "GIS_model_destination": self.gis_model_destination,
            "EM_rule": [r.to_dict() for r in self.rules],
        }


def rules_from_stage(stage: Dict[str, Any]) -> List[ElementRule]:
    return [ElementRule.from_dict(r) for r in stage.get("rule", [])]


def ruleset_from_stage(stage: Dict[str, Any]) -> EM_ruleset:
    """Build the ISO 19166 ``EM_ruleset`` object for a pipeline EM stage."""
    return EM_ruleset.from_stage(stage)


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
