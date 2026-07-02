"""
B2GM property helpers.

Thin helper layer around the :mod:`B2GM_model` ``property`` / ``property_set``
classes used when translating IFC property sets into the B2GM conceptual model.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

from typing import Any

from B2GM_model import PropertyType, property, property_set


def value_type(value: Any) -> str:
    """Return the B2GM property type (``integer`` / ``real`` / ``string``)."""
    return PropertyType.of(value)


def make_property(name: str, value: Any, data_type: str = "") -> property:
    """Create a :class:`B2GM_model.property` inferring the type when omitted."""
    return property(name, value, data_type or value_type(value))


def make_property_set(name: str, props: dict, set_type: str = "general") -> property_set:
    """Build a :class:`B2GM_model.property_set` from a ``{name: value}`` dict."""
    ps = property_set(name, set_type)
    for key, val in props.items():
        ps.add(make_property(key, val))
    return ps


if __name__ == "__main__":
    ps = make_property_set("Pset_WallCommon", {"IsExternal": "T", "Height": 3.0, "Count": 2})
    print(ps.to_dict())
