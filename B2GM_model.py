"""
B2GM conceptual data model (ISO 19166 - BIM to GIS conceptual Mapping).

This module implements the common conceptual model that is shared by both the
BIM side and the GIS side of the mapping, following the ISO/TS 19166 B2GM
conceptual framework (see ``doc/fig1.JPG``)::

    model  (BIM_model / GIS_model)
      +-- element *            (name, code, type)
      |     +-- geometry *     --> B-rep (brep)
      |     +-- property_set * (name, type: {system, general})
      |     |     +-- property *   (name, type: {integer, real, string}, value)
      |     +-- relationship *  (name, type: {association, dependency, generalization})
      |     +-- LOD             (name)  -- only on the GIS side
      +-- runtime              (type)

The classes deliberately keep the lower-case names used by the original
``B2GM_BIM`` / ``B2GM_GIS`` modules (``model`` is used there as a base class),
while providing convenience constructors and (de)serialisation helpers.

Author:
    Taewook Kang (laputa99999@gmail.com)

Date:
    2024-01-02 (reconstructed 2026-07)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations (kept as plain string constants to stay dependency free)
# ---------------------------------------------------------------------------
class PropertyType:
    INTEGER = "integer"
    REAL = "real"
    STRING = "string"

    @staticmethod
    def of(value: Any) -> str:
        """Infer the B2GM property type from a Python value."""
        if isinstance(value, bool):
            # bool is a subclass of int; treat it as a string flag.
            return PropertyType.STRING
        if isinstance(value, int):
            return PropertyType.INTEGER
        if isinstance(value, float):
            return PropertyType.REAL
        return PropertyType.STRING


class PropertySetType:
    SYSTEM = "system"
    GENERAL = "general"


class RelationshipType:
    ASSOCIATION = "association"
    DEPENDENCY = "dependency"
    GENERALIZATION = "generalization"


# ---------------------------------------------------------------------------
# Core conceptual classes
# ---------------------------------------------------------------------------
class property:  # noqa: N801 - keep original lower-case conceptual name
    """A single named value with a B2GM data type."""

    def __init__(self, name: str = "", value: Any = "", data_type: str = ""):
        self.name = name
        self.value = value
        self.data_type = data_type or PropertyType.of(value)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "type": self.data_type}

    def __repr__(self) -> str:
        return f"property(name={self.name!r}, value={self.value!r}, type={self.data_type!r})"


class property_set:  # noqa: N801
    """A named collection of :class:`property` objects."""

    def __init__(self, name: str = "", set_type: str = PropertySetType.GENERAL):
        self.name = name
        self.type = set_type
        self.pset: List[property] = []

    def add(self, prop: property) -> property:
        self.pset.append(prop)
        return prop

    def add_value(self, name: str, value: Any, data_type: str = "") -> property:
        return self.add(property(name, value, data_type))

    def get(self, name: str) -> Optional[property]:
        for p in self.pset:
            if p.name == name:
                return p
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "pset": [p.to_dict() for p in self.pset],
        }

    def __iter__(self):
        return iter(self.pset)

    def __len__(self) -> int:
        return len(self.pset)


class brep:  # noqa: N801
    """A minimal boundary representation (list of 3D points / faces)."""

    def __init__(self, points: Optional[List] = None, faces: Optional[List] = None):
        self.points = points if points is not None else []
        self.faces = faces if faces is not None else []

    def to_dict(self) -> Dict[str, Any]:
        return {"points": self.points, "faces": self.faces}


class geometry:  # noqa: N801
    """Geometry of an element, optionally holding a boundary representation."""

    def __init__(self, geom_type: str = "", brep_obj: Optional[brep] = None):
        self.type = geom_type
        self.brep = brep_obj
        self.points: List = []
        # raw source references / attributes (e.g. IfcExtrudedAreaSolid data)
        self.attributes: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "points": self.points,
            "brep": self.brep.to_dict() if self.brep else None,
            "attributes": self.attributes,
        }


class relationship:  # noqa: N801
    """A typed relationship between elements."""

    def __init__(self, name: str = "", rel_type: str = RelationshipType.ASSOCIATION):
        self.name = name
        self.type = rel_type
        self.related_objects: List[Any] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "related_objects": [str(o) for o in self.related_objects],
        }


class LOD:  # noqa: N801
    """Level of Detail descriptor for the GIS side (LOD0..LOD4)."""

    def __init__(self, name: str = ""):
        self.name = name

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name}


class runtime:  # noqa: N801
    """Runtime metadata attached to a model."""

    def __init__(self, type: str = ""):
        self.type = type

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type}


class object:  # noqa: A003, N801 - conceptual base object
    """Base object with identity (name / guid / description)."""

    def __init__(self, name: str = "", guid: str = "", description: str = ""):
        self.name = name
        self.guid = guid
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "guid": self.guid,
            "description": self.description,
        }


class element(object):  # noqa: N801
    """An element (feature) of a model with geometry, psets and relations."""

    def __init__(self, name: str = "", guid: str = "", description: str = ""):
        super().__init__(name, guid, description)
        self.code: str = name
        self.type: str = "struct"
        self.geometries: List[geometry] = []
        self.property_sets: List[property_set] = []
        self.relationships: List[relationship] = []
        self.lod: Optional[LOD] = None

    def add_property_set(self, pset: property_set) -> property_set:
        self.property_sets.append(pset)
        return pset

    def add_geometry(self, geom: geometry) -> geometry:
        self.geometries.append(geom)
        return geom

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "code": self.code,
                "type": self.type,
                "pset": {ps.name: {p.name: p.value for p in ps} for ps in self.property_sets},
                "geometries": [g.to_dict() for g in self.geometries],
                "relationships": [r.to_dict() for r in self.relationships],
                "lod": self.lod.to_dict() if self.lod else None,
            }
        )
        return d


class model:  # noqa: N801
    """Container for a set of elements and relationships.

    Used both as a concrete conceptual container and (historically) as the base
    class of :class:`B2GM_BIM.BIM` and :class:`B2GM_GIS.GIS`, where the loaded
    source dataset is kept in ``self.model_data``.
    """

    def __init__(self):
        self.elements: List[element] = []
        self.relationships: List[relationship] = []
        self.runtime: Optional[runtime] = None
        # populated by subclasses (BIM / GIS) with the raw source dataset
        self.model_data: Any = None

    def add(self, e: element) -> element:
        self.elements.append(e)
        return e

    def to_dict(self) -> Dict[str, Any]:
        return {
            "elements": [e.to_dict() for e in self.elements],
            "relationships": [r.to_dict() for r in self.relationships],
            "runtime": self.runtime.to_dict() if self.runtime else None,
        }


def test():
    m = model()
    e = m.add(element(name="IfcWall", guid="0001"))
    ps = e.add_property_set(property_set("Pset_WallCommon", PropertySetType.GENERAL))
    ps.add_value("IsExternal", True)
    ps.add_value("Height", 3.0)
    assert m.to_dict()["elements"][0]["name"] == "IfcWall"
    print(m.to_dict())


if __name__ == "__main__":
    test()
