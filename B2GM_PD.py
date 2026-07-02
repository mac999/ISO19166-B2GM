"""
B2GM PD - Perspective Definition (ISO 19166 B2GM, stage 1).

The Perspective Definition ("B2G PD" in ``doc/fig1.JPG``) selects the required
subset of a BIM/IFC dataset before it is mapped to GIS.  It is expressed with
three views:

* ``data_view``   - which classes/properties are required (a filter),
* ``logic_view``  - optional external logic applied to the selected data,
* ``style_view``  - which classes/properties drive styling.

This module turns a pipeline ``stage`` dict (see ``B2GM_example.json``) into
typed objects and implements the filter matching used to select elements.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class Filter:
    """A single property filter (regular-expression based)."""

    def __init__(self, name: str = ".*", value: str = ".*", data_type: str = ".*"):
        self.name = name
        self.value = value
        self.type = data_type

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Filter":
        return cls(d.get("name", ".*"), d.get("value", ".*"), d.get("type", ".*"))

    @staticmethod
    def _matches(pattern: str, text: str) -> bool:
        if pattern is None or pattern == "":
            return True
        return re.search(pattern, str(text)) is not None

    def matches(self, prop_name: str, prop_value: Any, prop_type: str) -> bool:
        return (
            self._matches(self.name, prop_name)
            and self._matches(self.value, prop_value)
            and self._matches(self.type, prop_type)
        )


class DataView:
    """Required data for a single IFC class plus its property filters."""

    def __init__(self, ifc_class: str = ".*", filters: Optional[List[Filter]] = None):
        self.ifc_class = ifc_class
        self.filters = filters if filters is not None else [Filter()]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DataView":
        filters = [Filter.from_dict(f) for f in d.get("filter", [])] or [Filter()]
        return cls(d.get("class", ".*"), filters)

    def class_matches(self, ifc_type: str) -> bool:
        # class patterns are full-match regex (use ".*Wall.*" for substrings)
        return re.fullmatch(self.ifc_class, str(ifc_type)) is not None


# StyleView shares the exact structure of DataView.
StyleView = DataView


class PerspectiveDefinition:
    """The full PD: data views, an optional logic view and style views."""

    def __init__(
        self,
        data_view: Optional[List[DataView]] = None,
        logic_view: str = "",
        style_view: Optional[List[StyleView]] = None,
    ):
        self.data_view = data_view if data_view is not None else []
        self.logic_view = logic_view
        self.style_view = style_view if style_view is not None else []

    @classmethod
    def from_stage(cls, stage: Dict[str, Any]) -> "PerspectiveDefinition":
        data_view = [DataView.from_dict(dv) for dv in stage.get("data_view", [])]
        style_view = [DataView.from_dict(sv) for sv in stage.get("style_view", [])]
        return cls(data_view, stage.get("logic_view", ""), style_view)

    def element_selected(self, obj: Dict[str, Any]) -> bool:
        """Return ``True`` if the given BIM object matches at least one data view.

        ``obj`` is a dict produced by :class:`B2GM_BIM.BIM` and is expected to
        carry an ``ifc_type`` (falling back to ``name``) and a ``pset`` mapping.
        """
        ifc_type = obj.get("ifc_type", obj.get("name", ""))
        psets = obj.get("pset", {}) or {}

        for dv in self.data_view:
            if not dv.class_matches(ifc_type):
                continue
            # An empty/`.*` property filter selects the whole class.
            for props in psets.values():
                for pname, pvalue in props.items():
                    ptype = type(pvalue).__name__
                    for flt in dv.filters:
                        if flt.matches(pname, pvalue, ptype):
                            return True
            # Class matched but no properties present -> still selected when the
            # filter is the permissive default.
            if not psets and all(
                f.name in ("", ".*") for f in dv.filters
            ):
                return True
        return False

    def select(self, objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter a list of BIM objects down to the perspective."""
        return [o for o in objects if self.element_selected(o)]


def from_stage(stage: Dict[str, Any]) -> PerspectiveDefinition:
    """Convenience wrapper matching the other B2GM stage modules."""
    return PerspectiveDefinition.from_stage(stage)


if __name__ == "__main__":
    pd = PerspectiveDefinition.from_stage(
        {
            "data_view": [{"class": "IfcBuilding", "filter": [{"name": ".*", "value": ".*", "type": ".*"}]}],
            "logic_view": "./calculate.exe",
            "style_view": [],
        }
    )
    sample = [
        {"ifc_type": "IfcBuilding", "name": "Duplex", "pset": {"Common": {"NumberOfStoreys": 4}}},
        {"ifc_type": "IfcWall", "name": "Wall", "pset": {"Common": {"IsExternal": "T"}}},
    ]
    print([o["name"] for o in pd.select(sample)])
