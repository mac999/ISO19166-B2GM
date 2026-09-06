"""
B2GM PD - Perspective Definition (ISO 19166 B2GM, stage 1).

The Perspective Definition ("B2G PD" in ``doc/fig1.JPG``) selects the required
subset of a BIM/IFC dataset before it is mapped to GIS.  It is expressed with
three views:

* ``data_view``   - which classes/properties are required (a filter),
* ``logic_view``  - external data joined in by an ETL module,
* ``style_view``  - which classes/properties drive styling.

This module turns a pipeline ``stage`` dict (see ``B2GM_example.json``) into
typed objects, selects elements, runs the logic view and applies the style
view's ``formattingOperation`` to the selected property values.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

import csv
import importlib
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# ISO 19166 B2G PD conceptual classes (XSD ``B2GM_PD.XSD``, Clause 7 / Table 4)
# ---------------------------------------------------------------------------
class PD_property:  # noqa: N801 - ISO 19166 PD_property complexType
    """A perspective property ``{name, value, type}`` (Table 4)."""

    def __init__(self, name: str = "", value: Any = "", type: str = ""):
        self.name = name
        self.value = value
        self.type = type

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "type": self.type}


class PD_category:  # noqa: N801 - ISO 19166 PD_category complexType
    """A group of similar properties: ``{name, PD_property*, PD_category}``."""

    def __init__(self, name: str = "", pd_properties: Optional[List[PD_property]] = None,
                 pd_category: Optional["PD_category"] = None):
        self.name = name
        self.PD_property = pd_properties if pd_properties is not None else []
        self.PD_category = pd_category  # nested sub-category (XSD 1..1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "PD_property": [p.to_dict() for p in self.PD_property],
            "PD_category": self.PD_category.to_dict() if self.PD_category else None,
        }


class PD_element:  # noqa: N801 - ISO 19166 PD_element complexType
    """A BIM element linked in the data view, keyed by ``objectGUID`` (PK)."""

    def __init__(self, objectGUID: str = "", pd_categories: Optional[List[PD_category]] = None):
        self.objectGUID = objectGUID
        self.PD_category = pd_categories if pd_categories is not None else []

    def to_dict(self) -> Dict[str, Any]:
        return {"objectGUID": self.objectGUID, "PD_category": [c.to_dict() for c in self.PD_category]}


class PD_data_view:  # noqa: N801 - ISO 19166 PD_data_view complexType
    """Data view = the set of selected ``PD_element`` (each with a GUID PK)."""

    def __init__(self, pd_elements: Optional[List[PD_element]] = None):
        self.PD_element = pd_elements if pd_elements is not None else []

    def to_dict(self) -> Dict[str, Any]:
        return {"PD_element": [e.to_dict() for e in self.PD_element]}


class PD_logic_view:  # noqa: N801 - ISO 19166 PD_logic_view complexType
    """Logic view = ``{external_data_source: URI, ETL_module: CharacterString}``.

    Accepts either the schema object (a dict) or the legacy single-string form
    (interpreted as the ETL module path).
    """

    def __init__(self, external_data_source: str = "", ETL_module: str = ""):
        self.external_data_source = external_data_source
        self.ETL_module = ETL_module

    @classmethod
    def from_value(cls, value: Any) -> "PD_logic_view":
        if isinstance(value, dict):
            return cls(value.get("external_data_source", ""),
                       value.get("ETL_module", value.get("etl_module", "")))
        return cls("", str(value or ""))

    def to_dict(self) -> Dict[str, Any]:
        return {"external_data_source": self.external_data_source, "ETL_module": self.ETL_module}

    def load_source(self) -> Dict[str, Dict[str, Any]]:
        """Read the external source into ``{GUID: {attribute: value}}``.

        JSON may be a ``{guid: {...}}`` map or a list of records carrying a
        ``GUID`` key; CSV needs a ``GUID`` column.
        """
        path = self.external_data_source
        if not path:
            return {}
        if not os.path.exists(path):
            logger.warning("logic_view source not found: %s", path)
            return {}
        if path.lower().endswith(".csv"):
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            return {r.get("GUID", ""): {k: v for k, v in r.items() if k != "GUID"} for r in rows}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {r.get("GUID", ""): {k: v for k, v in r.items() if k != "GUID"} for r in data}
        return {k: dict(v) for k, v in (data or {}).items()}

    def run(self, objects: List[Dict[str, Any]], pset_name: str = "PD_logic") -> List[Dict[str, Any]]:
        """Apply the logic view to the selected elements.

        ``ETL_module`` is ``"module:function"``; the function is called as
        ``fn(objects, source)`` and returns the transformed objects.  Without a
        module the external source is joined onto elements by GUID.
        """
        source = self.load_source()
        module_ref = (self.ETL_module or "").strip()
        if module_ref:
            if ":" not in module_ref:
                logger.warning("ETL_module must be 'module:function', got %r", module_ref)
                return objects
            module_name, _, func_name = module_ref.partition(":")
            try:
                func = getattr(importlib.import_module(module_name), func_name)
            except Exception as exc:
                logger.warning("ETL_module %s unavailable: %s", module_ref, exc)
                return objects
            result = func(objects, source)
            logger.info("logic_view ETL %s applied to %d elements", module_ref, len(objects))
            return result if result is not None else objects
        if not source:
            return objects
        joined = 0
        for obj in objects:
            extra = source.get(obj.get("GUID", ""))
            if not extra:
                continue
            obj.setdefault("pset", {}).setdefault(pset_name, {}).update(extra)
            joined += 1
        logger.info("logic_view joined %d elements from %s", joined, self.external_data_source)
        return objects


def _round(value: Any, digits: str = "0") -> Any:
    try:
        result = round(float(value), int(digits))
    except (TypeError, ValueError):
        return value
    return int(result) if int(digits) <= 0 else result


def _scale(value: Any, factor: str = "1") -> Any:
    try:
        return float(value) * float(factor)
    except (TypeError, ValueError):
        return value


# formattingOperation vocabulary: "name" or "name:arg[:arg]"
FORMATTERS: Dict[str, Callable[..., Any]] = {
    "upper": lambda v: str(v).upper(),
    "lower": lambda v: str(v).lower(),
    "title": lambda v: str(v).title(),
    "strip": lambda v: str(v).strip(),
    "round": _round,
    "scale": _scale,
    "prefix": lambda v, text="": f"{text}{v}",
    "suffix": lambda v, text="": f"{v}{text}",
    "replace": lambda v, old="", new="": str(v).replace(old, new),
    "format": lambda v, spec="{}": spec.format(v),
    "truncate": lambda v, n="20": str(v)[: int(n)],
}


def format_value(value: Any, operation: str) -> Any:
    """Apply a ``formattingOperation`` string to a property value."""
    if not operation:
        return value
    for step in str(operation).split("|"):
        name, _, rest = step.strip().partition(":")
        formatter = FORMATTERS.get(name)
        if formatter is None:
            raise KeyError(f"unknown formattingOperation: {name!r}; known: {sorted(FORMATTERS)}")
        args = rest.split(":") if rest else []
        value = formatter(value, *args)
    return value


class PD_property_style:  # noqa: N801 - ISO 19166 PD_property_style complexType
    """Style rule ``{category, property, formattingOperation}`` (Table 4).

    ``category``/``property`` are regular expressions matched against a property
    set name and a property name; ``formattingOperation`` is a ``|``-separated
    chain from :data:`FORMATTERS` (e.g. ``"round:1|suffix: m"``).
    """

    def __init__(self, category: str = "", property: str = "", formattingOperation: str = ""):
        self.category = category
        self.property = property
        self.formattingOperation = formattingOperation

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PD_property_style":
        return cls(d.get("category", ""), d.get("property", ""), d.get("formattingOperation", ""))

    def to_dict(self) -> Dict[str, Any]:
        return {"category": self.category, "property": self.property,
                "formattingOperation": self.formattingOperation}

    def matches(self, category: str, prop: str) -> bool:
        return (re.fullmatch(self.category or ".*", str(category)) is not None
                and re.fullmatch(self.property or ".*", str(prop)) is not None)

    def apply(self, value: Any) -> Any:
        return format_value(value, self.formattingOperation)


class PD_style_view:  # noqa: N801 - ISO 19166 PD_sytle_view complexType
    """Style view = a container of ``PD_property_style`` objects."""

    def __init__(self, pd_property_styles: Optional[List[PD_property_style]] = None):
        self.PD_property_style = pd_property_styles if pd_property_styles is not None else []

    def to_dict(self) -> Dict[str, Any]:
        return {"PD_property_style": [s.to_dict() for s in self.PD_property_style]}

    def apply(self, obj: Dict[str, Any]) -> Dict[str, Any]:
        """Format the element's property values in place; returns what changed."""
        changed: Dict[str, Any] = {}
        for category, props in (obj.get("pset") or {}).items():
            for prop, value in list((props or {}).items()):
                for style in self.PD_property_style:
                    if not style.matches(category, prop):
                        continue
                    try:
                        formatted = style.apply(value)
                    except Exception as exc:
                        logger.warning("style %s.%s failed: %s", category, prop, exc)
                        continue
                    if formatted != value:
                        props[prop] = formatted
                        changed[f"{category}.{prop}"] = formatted
                    break
        return changed


class PerspectiveDefinition:
    """The full PD (ISO 19166 ``PD`` complexType).

    Functional fields (``data_view``/``style_view`` filters, ``logic_view``
    string) drive the actual element selection, while the schema-conformant
    members (``name``, ``BIM_model_destination``, ``PD_data_view``,
    ``PD_logic_view``, ``PD_style_view``) mirror ``B2GM_PD.XSD``.  After
    :meth:`select`, ``PD_data_view`` is populated with a ``PD_element`` (carrying
    the ``objectGUID`` PK) for every selected element.
    """

    def __init__(
        self,
        data_view: Optional[List[DataView]] = None,
        logic_view: str = "",
        style_view: Optional[List[StyleView]] = None,
        name: str = "",
        bim_model_destination: str = "",
        pd_style_view: Optional[PD_style_view] = None,
    ):
        self.data_view = data_view if data_view is not None else []
        self.logic_view = logic_view
        self.style_view = style_view if style_view is not None else []
        # ISO 19166 PD members
        self.name = name
        self.BIM_model_destination = bim_model_destination
        self.PD_data_view = PD_data_view()
        self.PD_logic_view = PD_logic_view.from_value(logic_view)
        self.PD_style_view = pd_style_view if pd_style_view is not None else PD_style_view()

    @classmethod
    def from_stage(cls, stage: Dict[str, Any]) -> "PerspectiveDefinition":
        data_view = [DataView.from_dict(dv) for dv in stage.get("data_view", [])]
        style_view = [DataView.from_dict(sv) for sv in stage.get("style_view", [])]
        # optional explicit property-style definitions (XSD PD_property_style)
        styles = [PD_property_style.from_dict(s) for s in stage.get("property_style", [])]
        return cls(
            data_view,
            stage.get("logic_view", ""),
            style_view,
            name=stage.get("name", ""),
            bim_model_destination=stage.get("BIM_model_destination", stage.get("output", "")),
            pd_style_view=PD_style_view(styles),
        )

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

    def style_selected(self, obj: Dict[str, Any]) -> bool:
        """Return ``True`` when a style view claims this element's class."""
        ifc_type = obj.get("ifc_type", obj.get("name", ""))
        return any(sv.class_matches(ifc_type) for sv in self.style_view)

    def apply_style(self, objects: List[Dict[str, Any]]) -> int:
        """Run the style view's ``formattingOperation`` over the elements it claims."""
        if not self.PD_style_view.PD_property_style:
            return 0
        styled = 0
        for obj in objects:
            if self.style_view and not self.style_selected(obj):
                continue
            changed = self.PD_style_view.apply(obj)
            if changed:
                obj["_style"] = changed
                styled += 1
        if styled:
            logger.info("style_view formatted %d elements", styled)
        return styled

    def categories_of(self, obj: Dict[str, Any]) -> List[PD_category]:
        """Build the ``PD_category`` list of an element from its property sets."""
        categories = []
        for name, props in (obj.get("pset") or {}).items():
            categories.append(PD_category(name, [
                PD_property(k, v, type(v).__name__) for k, v in (props or {}).items()
            ]))
        return categories

    def select(self, objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter BIM objects down to the perspective and run the logic/style views.

        :attr:`PD_data_view` is populated with a ``PD_element`` per selected
        element, carrying the ``objectGUID`` primary key (ISO 19166 PD1) and its
        ``PD_category`` groups.
        """
        selected = [o for o in objects if self.element_selected(o)]
        selected = self.PD_logic_view.run(selected)
        self.apply_style(selected)
        self.PD_data_view = PD_data_view(
            [PD_element(o.get("GUID", ""), self.categories_of(o)) for o in selected]
        )
        return selected


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
