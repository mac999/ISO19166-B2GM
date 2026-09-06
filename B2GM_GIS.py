"""
B2GM GIS side - serialise mapped BIM elements to a **renderable** CityGML 2.0 file.

Earlier revisions wrote element attributes only (no geometry), so a CityGML
viewer had nothing to draw.  This version emits standards-compliant CityGML 2.0
with real geometry:

* a ``gml:boundedBy``/``gml:Envelope`` computed from the model extent;
* one ``bldg:Building`` grouping every mapped element;
* geometry-bearing elements become boundary surfaces (``bldg:WallSurface``,
  ``bldg:RoofSurface``, ...) with ``bldg:lod2MultiSurface`` triangle meshes, or
  ``bldg:BuildingInstallation`` (``bldg:lod2Geometry``) for non-surface features;
* element attributes (IFC type, GUID, LoD, property-set values) are preserved as
  ``gen:stringAttribute`` generic attributes.

Geometry comes from :class:`B2GM_BIM.BIM`, which attaches
``obj['geometry'] = {'verts': [...], 'faces': [...]}`` (flat lists, world
coordinates).  Elements without geometry are still listed (as generic
attributes on the building) so nothing is silently lost.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr

import B2GM_element
import B2GM_model
import B2GM_property  # noqa: F401 - kept for backward-compatible imports

# CityGML 2.0 module namespaces.
NS = {
    "core": "http://www.opengis.net/citygml/2.0",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "gen": "http://www.opengis.net/citygml/generics/2.0",
    "luse": "http://www.opengis.net/citygml/landuse/2.0",
    "gml": "http://www.opengis.net/gml",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

SCHEMA_LOCATION = " ".join([
    "http://www.opengis.net/citygml/2.0",
    "http://schemas.opengis.net/citygml/2.0/cityGMLBase.xsd",
    "http://www.opengis.net/citygml/building/2.0",
    "http://schemas.opengis.net/citygml/building/2.0/building.xsd",
    "http://www.opengis.net/citygml/generics/2.0",
    "http://schemas.opengis.net/citygml/generics/2.0/generics.xsd",
    "http://www.opengis.net/citygml/landuse/2.0",
    "http://schemas.opengis.net/citygml/landuse/2.0/landUse.xsd",
])

# EM destinations that are CityGML 2.0 thematic boundary surfaces.
BOUNDARY_SURFACES = {
    "WallSurface",
    "RoofSurface",
    "GroundSurface",
    "FloorSurface",
    "CeilingSurface",
    "ClosureSurface",
    "OuterFloorSurface",
    "OuterCeilingSurface",
}

# Where each EM destination belongs in a CityGML 2.0 document:
# (role, qualified element name, containing property, geometry property).
# ``role`` drives nesting: boundary surfaces and installations hang off the
# building, openings off their host boundary surface, rooms off interiorRoom,
# and "top" features are their own core:cityObjectMember.
PLACEMENT: Dict[str, Tuple[str, str, str, str]] = {
    **{name: ("boundary", f"bldg:{name}", "bldg:boundedBy", "bldg:lod2MultiSurface")
       for name in BOUNDARY_SURFACES},
    "Window": ("opening", "bldg:Window", "bldg:opening", "bldg:lod3MultiSurface"),
    "Door": ("opening", "bldg:Door", "bldg:opening", "bldg:lod3MultiSurface"),
    "Room": ("room", "bldg:Room", "bldg:interiorRoom", "bldg:lod4MultiSurface"),
    "BuildingInstallation": ("installation", "bldg:BuildingInstallation",
                             "bldg:outerBuildingInstallation", "bldg:lod2Geometry"),
    "IntBuildingInstallation": ("installation", "bldg:IntBuildingInstallation",
                                "bldg:interiorBuildingInstallation", "bldg:lod4Geometry"),
    "BuildingPart": ("part", "bldg:BuildingPart",
                     "bldg:consistsOfBuildingPart", "bldg:lod2MultiSurface"),
    "LandUse": ("top", "luse:LandUse", "core:cityObjectMember", "luse:lod1MultiSurface"),
    "GenericCityObject": ("top", "gen:GenericCityObject", "core:cityObjectMember",
                          "gen:lod1Geometry"),
}

# A boundary surface may only carry bldg:opening from LOD3 up.
OPENING_HOST_LOD = "bldg:lod3MultiSurface"

SUPPORTED_VERSIONS = ("2.0", "3.0")
DEFAULT_VERSION = "2.0"


def normalise_version(version: Any) -> str:
    """Accept "3", "3.0", "CityGML 3.0"; raise on anything unsupported."""
    text = str(version or DEFAULT_VERSION).lower().replace("citygml", "").strip()
    if text in ("2", "2.0"):
        return "2.0"
    if text in ("3", "3.0"):
        return "3.0"
    raise ValueError(
        f"unsupported CityGML version: {version!r}; expected one of {SUPPORTED_VERSIONS}")


def version_from_stage(stage: Optional[Dict[str, Any]], default: str = DEFAULT_VERSION) -> str:
    """Read ``citygml_version`` from a pipeline stage (falls back to ``default``)."""
    if not stage:
        return normalise_version(default)
    return normalise_version(stage.get("citygml_version", default))

# destinations that identify the building itself (not a sub-feature).
BUILDING_DESTINATIONS = {"CityModel.Building", "Building", "bldg:Building"}

# keys that are internal book-keeping rather than payload properties
_META_KEYS = {"pset", "ifc_type", "geometry", "_destination", "_lod", "_pset_operation",
              "_lod_geometry", "_lod_operation", "_style"}


def sanitize_tag(name: str) -> str:
    """Turn an arbitrary property name into a valid XML tag / attribute name.

    Spaces and other invalid characters become underscores; a leading digit or
    invalid start character is prefixed with ``p_``.  Empty names become ``prop``.
    """
    tag = re.sub(r"[^A-Za-z0-9_.\-]", "_", str(name).strip())
    if not tag:
        return "prop"
    if not re.match(r"[A-Za-z_]", tag[0]):
        tag = "p_" + tag
    return tag


def gml_id(value: str, prefix: str = "id") -> str:
    """Return a valid ``gml:id`` (NCName) derived from an IFC GUID or name."""
    ident = re.sub(r"[^A-Za-z0-9_.\-]", "_", str(value).strip())
    if not ident or not re.match(r"[A-Za-z_]", ident[0]):
        ident = f"{prefix}_{ident}"
    return ident


def element_geometry(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Geometry to serialise: the LM operator result when present, else source."""
    return obj.get("_lod_geometry") or obj.get("geometry")


def _reshape(geometry: Dict[str, Any]) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
    """Return ``(vertices, faces)`` from a flat ``{'verts':[...], 'faces':[...]}``."""
    flat_v = geometry.get("verts") or []
    flat_f = geometry.get("faces") or []
    verts = [tuple(flat_v[i : i + 3]) for i in range(0, len(flat_v) - 2, 3)]
    faces = [tuple(flat_f[i : i + 3]) for i in range(0, len(flat_f) - 2, 3)]
    return verts, faces


class GIS(B2GM_model.model):
    def parse(self, fname):  # noqa: D401 - GIS parsing not implemented
        """Reading CityGML back into the model is not implemented."""
        return None

    # -- public API ---------------------------------------------------------
    def store(self, fname: str, objects: List[Dict[str, Any]], stage: Dict[str, Any],
              srs_name: Optional[str] = None, version: str = DEFAULT_VERSION) -> int:
        """Write ``objects`` (matching the EM rules of ``stage``) as CityGML.

        ``srs_name`` is the destination CRS the CM stage placed the geometry in;
        it is written on the envelope so the file is georeferenced.  ``version``
        selects the output schema ("2.0" or "3.0"); 3.0 is delegated to
        :mod:`B2GM_citygml3`, which has the restructured building model (real
        storeys, con:fillingSurface openings, GML 3.2).  Returns the number of
        features written.
        """
        version = normalise_version(version)
        rules = B2GM_element.rules_from_stage(stage)

        # resolve a destination for every object, dropping unmatched ones only
        # when rules exist (LM passes empty rules and relies on _destination).
        resolved: List[Tuple[Dict[str, Any], str]] = []
        for obj in objects:
            destination = obj.get("_destination")
            if destination is None:
                destination = B2GM_element.map_element(obj, rules)
            if destination is None:
                if rules:
                    continue
                destination = "GenericCityObject"
            resolved.append((obj, destination))

        if version == "3.0":
            import B2GM_citygml3

            return B2GM_citygml3.store(
                fname, resolved, srs_name,
                nest_by_storey=(stage or {}).get("nest_by_storey", True))

        lower, upper = self._envelope(resolved)

        self._used_ids = set()
        with open(fname, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write("<core:CityModel")
            for prefix, uri in NS.items():
                f.write(f'\n    xmlns:{prefix}="{uri}"')
            f.write(f'\n    xsi:schemaLocation={quoteattr(SCHEMA_LOCATION)}')
            f.write(">\n")

            self._srs_name = srs_name
            f.write("  <gml:boundedBy>\n")
            srs = f' srsName={quoteattr(srs_name)}' if srs_name else ""
            f.write(f'    <gml:Envelope{srs} srsDimension="3">\n')
            f.write(f'      <gml:lowerCorner>{_fmt3(lower)}</gml:lowerCorner>\n')
            f.write(f'      <gml:upperCorner>{_fmt3(upper)}</gml:upperCorner>\n')
            f.write("    </gml:Envelope>\n")
            f.write("  </gml:boundedBy>\n")

            written = self._write_building(f, resolved)

            f.write("</core:CityModel>\n")
        return written

    def save(self, fname: str, objects: List[Dict[str, Any]], stage: Optional[Dict[str, Any]] = None) -> str:
        """Serialise mapped GIS objects to JSON per ``B2GM_GIS_model.XSD``.

        The document mirrors the ISO 19166 GIS model UML: a ``GIS_model`` holds
        ``GIS_element`` entries, each with ``runtime`` / ``LOD`` / ``relationship``
        / ``property_set`` (member order follows the XSD).  ``runtime.type`` is
        the mapped GIS class (EM destination), and each ``LOD`` carries its name
        plus the element geometry as B-rep (GM3-style).

        The destination is taken from ``_destination`` (set by EM) or resolved
        from the ``stage`` rules; elements with no destination are skipped when
        rules are present (mirroring :meth:`store`).
        """
        rules = B2GM_element.rules_from_stage(stage) if stage else []
        elements = []
        for o in objects:
            destination = o.get("_destination")
            if destination is None and rules:
                destination = B2GM_element.map_element(o, rules)
            if destination is None:
                if rules:
                    continue
                destination = o.get("ifc_type", "")
            elements.append(
                {
                    "runtime": {"type": destination},
                    "LOD": [
                        {
                            "name": o.get("_lod", "LOD1"),
                            "geometry": B2GM_model.geometry_json(element_geometry(o)),
                        }
                    ],
                    "relationship": B2GM_model.relationships_json(o.get("relationship")),
                    "property_set": B2GM_model.element_property_sets_json(o),
                }
            )
        document = {"GIS_model": {"GIS_element": elements}}
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(document, f, indent=2, ensure_ascii=False, default=str)
        logging.info("GIS model saved (%d elements) -> %s", len(elements), fname)
        return fname

    def load(self, fname: str) -> List[Dict[str, Any]]:
        """Load a ``B2GM_GIS_model.XSD`` JSON file written by :meth:`save`.

        Reconstructs the internal mapped-object dicts, restoring ``_destination``
        (from ``runtime.type``), ``_lod`` and ``geometry`` (from the first
        ``LOD``), ``pset``, ``relationship`` and the system ``name`` / ``GUID`` /
        ``predefined_type``.  The result can be fed straight back to
        :meth:`store` (to re-emit CityGML) or :meth:`save`.
        """
        with open(fname, "r", encoding="utf-8") as f:
            document = json.load(f)

        elements = (document.get("GIS_model") or {}).get("GIS_element", [])
        objects: List[Dict[str, Any]] = []
        for e in elements:
            system, user = B2GM_model.property_sets_from_json(e.get("property_set"))
            lod = (e.get("LOD") or [{}])[0]
            obj: Dict[str, Any] = {
                "name": system.get("name", ""),
                "code": system.get("name", ""),
                "predefined_type": system.get("predefined_type", ""),
                "type": "struct",
                "GUID": system.get("GUID", ""),
                "_destination": (e.get("runtime") or {}).get("type", ""),
                "_lod": lod.get("name", ""),
                "pset": user,
                "relationship": e.get("relationship", []),
            }
            geom = B2GM_model.geometry_from_json(lod.get("geometry"))
            if geom:
                obj["geometry"] = geom
            objects.append(obj)

        logging.info("GIS model loaded (%d elements) <- %s", len(objects), fname)
        return objects

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _envelope(resolved) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        seen = False
        for obj, _ in resolved:
            geom = element_geometry(obj)
            if not geom:
                continue
            verts, _faces = _reshape(geom)
            for x, y, z in verts:
                seen = True
                lo[0], lo[1], lo[2] = min(lo[0], x), min(lo[1], y), min(lo[2], z)
                hi[0], hi[1], hi[2] = max(hi[0], x), max(hi[1], y), max(hi[2], z)
        if not seen:
            return (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
        return tuple(lo), tuple(hi)

    # -- document structure -------------------------------------------------
    @staticmethod
    def _opening_hosts(resolved) -> Dict[str, str]:
        """Map an opening-filling element (window/door) to its host wall GUID.

        IFC records ``wall -voids-> opening`` and ``window -fills-> opening``, so
        the two chain through the opening's GUID.
        """
        opening_to_host: Dict[str, str] = {}
        for obj, _ in resolved:
            for rel in obj.get("relationship") or []:
                if rel.get("name") == "voids":
                    guid = (rel.get("related") or {}).get("guid")
                    if guid and obj.get("GUID"):
                        opening_to_host[guid] = obj["GUID"]
        hosts: Dict[str, str] = {}
        for obj, _ in resolved:
            for rel in obj.get("relationship") or []:
                if rel.get("name") == "fills":
                    guid = (rel.get("related") or {}).get("guid")
                    host = opening_to_host.get(guid)
                    if host and obj.get("GUID"):
                        hosts[obj["GUID"]] = host
        return hosts

    def _write_building(self, f, resolved) -> int:
        building_obj = next((o for o, d in resolved if d in BUILDING_DESTINATIONS), None)
        b_guid = (building_obj or {}).get("GUID") if building_obj else None
        b_name = (building_obj or {}).get("name", "Building") if building_obj else "Building"

        hosts = self._opening_hosts(resolved)

        # bucket every element by the role its destination plays in CityGML
        boundaries: List[Tuple[Dict[str, Any], str]] = []
        openings: Dict[str, List[Tuple[Dict[str, Any], str]]] = {}
        loose_openings: List[Tuple[Dict[str, Any], str]] = []
        rooms: List[Tuple[Dict[str, Any], str]] = []
        installations: List[Tuple[Dict[str, Any], str]] = []
        parts: List[Tuple[Dict[str, Any], str]] = []
        top: List[Tuple[Dict[str, Any], str]] = []
        attribute_only: List[Tuple[Dict[str, Any], str]] = []

        for obj, destination in resolved:
            if obj is building_obj:
                continue
            role = (PLACEMENT.get(destination) or ("", "", "", ""))[0]
            if role == "top":
                # a top-level feature keeps its own member even without geometry
                top.append((obj, destination))
            elif not element_geometry(obj):
                # no geometry: keep it discoverable as an attribute of the building
                attribute_only.append((obj, destination))
            elif role == "boundary":
                boundaries.append((obj, destination))
            elif role == "opening":
                host = hosts.get(obj.get("GUID", ""))
                if host:
                    openings.setdefault(host, []).append((obj, destination))
                else:
                    loose_openings.append((obj, destination))
            elif role == "room":
                rooms.append((obj, destination))
            elif role == "installation":
                installations.append((obj, destination))
            elif role == "part":
                parts.append((obj, destination))
            else:
                # unknown destination with geometry: never drop it
                top.append((obj, destination))

        written = 1
        f.write("  <core:cityObjectMember>\n")
        f.write(f'    <bldg:Building gml:id="{self._id(b_guid or "building_1", "bldg")}">\n')
        f.write(f"      <gml:name>{escape(str(b_name))}</gml:name>\n")

        if building_obj is not None:
            self._write_generic_attrs(f, building_obj, "CityModel.Building", indent="      ")
        for obj, destination in attribute_only:
            self._write_generic_attrs(f, obj, destination, indent="      ")

        if building_obj is not None:
            b_geom = element_geometry(building_obj)
            if b_geom:
                lod = str(building_obj.get("_lod", "LOD1")).upper()
                tag = "bldg:lod1MultiSurface" if lod in ("LOD0", "LOD1") else "bldg:lod2MultiSurface"
                self._write_geometry_property(f, tag, b_geom, "      ")

        # AbstractBuildingType sequences its children: geometry, then
        # outerBuildingInstallation, boundedBy, interiorRoom, consistsOfBuildingPart.
        # an opening with no host wall would be lost, so it becomes an installation
        for obj, destination in loose_openings:
            written += self._write_member(f, obj, destination, "      ",
                                          placed_as="BuildingInstallation")
        for obj, destination in installations:
            written += self._write_member(f, obj, destination, "      ")
        for obj, destination in boundaries:
            written += self._write_boundary_surface(
                f, obj, destination, openings.get(obj.get("GUID", ""), []))
        for obj, destination in rooms:
            written += self._write_member(f, obj, destination, "      ")
        for obj, destination in parts:
            written += self._write_member(f, obj, destination, "      ")

        f.write("    </bldg:Building>\n")
        f.write("  </core:cityObjectMember>\n")

        for obj, destination in top:
            written += self._write_top_level(f, obj, destination)
        return written

    def _write_boundary_surface(self, f, obj, destination, openings) -> int:
        element, container, geometry_property = PLACEMENT[destination][1:]
        # bldg:opening is only allowed from LOD3, so a hosting surface moves up
        if openings:
            geometry_property = OPENING_HOST_LOD
        f.write(f"      <{container}>\n")
        f.write(f'        <{element} gml:id="{self._id(obj.get("GUID") or destination, "s")}">\n')
        f.write(f"          <gml:name>{escape(str(obj.get('name', destination)))}</gml:name>\n")
        self._write_generic_attrs(f, obj, destination, indent="          ")
        self._write_geometry_property(f, geometry_property, element_geometry(obj), "          ")
        written = 1
        for opening, opening_destination in openings:
            written += self._write_member(f, opening, opening_destination, "          ")
        f.write(f"        </{element}>\n")
        f.write(f"      </{container}>\n")
        return written

    def _write_member(self, f, obj, destination, indent, placed_as=None) -> int:
        """Write one nested feature (opening / room / installation / part).

        ``placed_as`` overrides where it goes -- an opening with no host wall
        cannot sit under bldg:opening, so it is written as an installation.
        """
        key = placed_as or destination
        _role, element, container, geometry_property = (
            PLACEMENT.get(key) or PLACEMENT["GenericCityObject"])
        f.write(f"{indent}<{container}>\n")
        f.write(f'{indent}  <{element} gml:id="{self._id(obj.get("GUID") or destination, "f")}">\n')
        f.write(f"{indent}    <gml:name>{escape(str(obj.get('name', destination)))}</gml:name>\n")
        self._write_generic_attrs(f, obj, destination, indent=f"{indent}    ")
        self._write_geometry_property(f, geometry_property, element_geometry(obj), f"{indent}    ")
        f.write(f"{indent}  </{element}>\n")
        f.write(f"{indent}</{container}>\n")
        return 1

    def _write_top_level(self, f, obj, destination) -> int:
        """Write a feature that is its own core:cityObjectMember."""
        placement = PLACEMENT.get(destination) or PLACEMENT["GenericCityObject"]
        _role, element, _container, geometry_property = placement
        f.write("  <core:cityObjectMember>\n")
        f.write(f'    <{element} gml:id="{self._id(obj.get("GUID") or destination, "o")}">\n')
        f.write(f"      <gml:name>{escape(str(obj.get('name', destination)))}</gml:name>\n")
        self._write_generic_attrs(f, obj, destination, indent="      ")
        self._write_geometry_property(f, geometry_property, element_geometry(obj), "      ")
        f.write(f"    </{element}>\n")
        f.write("  </core:cityObjectMember>\n")
        return 1

    def _write_geometry_property(self, f, property_name, geom, indent):
        if not geom:
            return
        f.write(f"{indent}<{property_name}>\n")
        self._write_multisurface(f, geom, indent=f"{indent}  ")
        f.write(f"{indent}</{property_name}>\n")

    def _write_multisurface(self, f, geom, indent="  "):
        verts, faces = _reshape(geom)
        srs = getattr(self, "_srs_name", None)
        attr = f' srsName={quoteattr(srs)}' if srs else ""
        f.write(f"{indent}<gml:MultiSurface{attr}>\n")
        for tri in faces:
            if len(tri) < 3:
                continue
            ring = list(tri) + [tri[0]]  # close the ring
            coords = " ".join(_fmt3(verts[i]) for i in ring if i < len(verts))
            f.write(f"{indent}  <gml:surfaceMember>\n")
            f.write(f"{indent}    <gml:Polygon>\n")
            f.write(f"{indent}      <gml:exterior>\n")
            f.write(f"{indent}        <gml:LinearRing>\n")
            f.write(f'{indent}          <gml:posList srsDimension="3">{coords}</gml:posList>\n')
            f.write(f"{indent}        </gml:LinearRing>\n")
            f.write(f"{indent}      </gml:exterior>\n")
            f.write(f"{indent}    </gml:Polygon>\n")
            f.write(f"{indent}  </gml:surfaceMember>\n")
        f.write(f"{indent}</gml:MultiSurface>\n")

    def _id(self, value: str, prefix: str) -> str:
        """A gml:id unique within the document (one element can yield several)."""
        base = gml_id(value, prefix=prefix)
        used = getattr(self, "_used_ids", None)
        if used is None:
            used = self._used_ids = set()
        candidate = base
        counter = 2
        while candidate in used:
            candidate = f"{base}_{counter}"
            counter += 1
        used.add(candidate)
        return candidate

    @staticmethod
    def _write_generic_attrs(f, obj, destination, indent="  "):
        """Emit IFC type / GUID / LoD / property-set values as gen:stringAttribute."""
        def attr(name: str, value: Any):
            f.write(f"{indent}<gen:stringAttribute name={quoteattr(str(name))}>\n")
            f.write(f"{indent}  <gen:value>{escape(str(value))}</gen:value>\n")
            f.write(f"{indent}</gen:stringAttribute>\n")

        if obj.get("ifc_type"):
            attr("ifc_type", obj["ifc_type"])
        if obj.get("predefined_type"):
            attr("predefined_type", obj["predefined_type"])
        if obj.get("GUID"):
            attr("GUID", obj["GUID"])
        attr("gis_class", destination)
        if obj.get("_lod"):
            attr("lod", obj["_lod"])

        pset = obj.get("pset", {}) or {}
        for pset_name, props in pset.items():
            for prop_name, prop_value in (props or {}).items():
                attr(f"{pset_name}.{prop_name}", prop_value)


def _fmt3(xyz) -> str:
    return " ".join(f"{float(c):.4f}" for c in xyz)


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
        },
        {
            "name": "Wall",
            "ifc_type": "IfcWallStandardCase",
            "GUID": "w1",
            "_destination": "WallSurface",
            "geometry": {"verts": [0, 0, 0, 1, 0, 0, 1, 0, 2], "faces": [0, 1, 2]},
        },
    ]
    stage = {"rule": [
        {"source": "IfcBuilding", "destination": "CityModel.Building"},
        {"source": "IfcWall.*", "destination": "WallSurface"},
    ]}
    n = gis.store("test_out.gml", objs, stage)
    print("features written:", n)


if __name__ == "__main__":
    test()
