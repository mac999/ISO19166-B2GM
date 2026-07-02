"""
B2GM GIS side - serialise mapped BIM elements to a (simplified) CityGML file.

The GIS model consumes the B2GM objects produced by :class:`B2GM_BIM.BIM`, and
the element-mapping rules of an EM stage, and writes a well-formed CityGML-like
XML document.  Element mapping (which IFC class becomes which GIS class) is
delegated to :mod:`B2GM_element`; LoD annotation (``_lod``) produced by
:mod:`B2GM_LM` is emitted as a ``<lod>`` element.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List
from xml.sax.saxutils import escape

import B2GM_element
import B2GM_model
import B2GM_property  # noqa: F401 - kept for backward-compatible imports

# keys that are internal book-keeping rather than payload properties
_META_KEYS = {"pset", "ifc_type", "_destination", "_lod", "_pset_operation"}


def sanitize_tag(name: str) -> str:
    """Turn an arbitrary property name into a valid XML tag name.

    Spaces and other invalid characters become underscores; a leading digit or
    invalid start character is prefixed with ``p_``.  Empty names become ``prop``.
    """
    tag = re.sub(r"[^A-Za-z0-9_.\-]", "_", str(name).strip())
    if not tag:
        return "prop"
    if not re.match(r"[A-Za-z_]", tag[0]):
        tag = "p_" + tag
    return tag


class GIS(B2GM_model.model):
    def parse(self, fname):  # noqa: D401 - GIS parsing not implemented
        """Reading CityGML back into the model is not implemented."""
        return None

    def store(self, fname: str, objects: List[Dict[str, Any]], stage: Dict[str, Any]):
        """Write ``objects`` matching the EM rules of ``stage`` to a CityGML file."""
        rules = B2GM_element.rules_from_stage(stage)
        default_dest = "cityObject"

        with open(fname, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<CityModel xmlns="http://www.opengis.net/citygml/3.0">\n')

            written = 0
            for obj in objects:
                # Prefer a destination already resolved by EM; else evaluate rules.
                destination = obj.get("_destination")
                if destination is None:
                    destination = B2GM_element.map_element(obj, rules)
                # With no rules at all, pass every element through (used by LM).
                if destination is None:
                    if rules:
                        continue
                    destination = default_dest

                dest_tag = sanitize_tag(destination)
                f.write("  <cityObjectMember>\n")
                f.write(f"    <{dest_tag}>\n")
                self._write_object(f, obj)
                f.write(f"    </{dest_tag}>\n")
                f.write("  </cityObjectMember>\n")
                written += 1

            f.write("</CityModel>\n")
        return written

    @staticmethod
    def _write_object(f, obj: Dict[str, Any]):
        for key, value in obj.items():
            if key in _META_KEYS:
                continue
            tag = sanitize_tag(key)
            f.write(f"      <{tag}>{escape(str(value))}</{tag}>\n")

        if obj.get("_lod"):
            f.write(f"      <lod>{escape(str(obj['_lod']))}</lod>\n")

        pset = obj.get("pset", {}) or {}
        for pset_name, pset_values in pset.items():
            ps_tag = sanitize_tag(pset_name)
            f.write(f'      <propertySet name="{escape(str(pset_name), {chr(34): "&quot;"})}">\n')
            for prop_name, prop_value in pset_values.items():
                tag = sanitize_tag(prop_name)
                f.write(f"        <{tag}>{escape(str(prop_value))}</{tag}>\n")
            f.write("      </propertySet>\n")


def test():
    gis = GIS()
    objs = [
        {
            "name": "Duplex",
            "ifc_type": "IfcBuilding",
            "code": "IfcBuilding",
            "GUID": "abc",
            "_lod": "LOD1",
            "pset": {"Common": {"Number Of Storeys": 4}},
        }
    ]
    stage = {"rule": [{"source": "IfcBuilding", "destination": "CityModel.Building"}]}
    n = gis.store("test_out.gml", objs, stage)
    print("written:", n)


if __name__ == "__main__":
    test()
