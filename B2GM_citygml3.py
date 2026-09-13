"""
B2GM CityGML 3.0 writer.

CityGML 3.0 restructured the building model, so the 2.0 writer in
:mod:`B2GM_GIS` cannot simply change namespaces:

* thematic surfaces hang off ``core:boundary`` (was ``bldg:boundedBy``) and live
  in the *construction* module;
* openings became ``con:fillingSurface`` -> ``con:Window`` / ``con:Door``;
* ``Room`` became ``bldg:BuildingRoom`` under ``bldg:buildingRoom``;
* there is a real ``bldg:Storey`` (under ``bldg:buildingSubdivision``), which
  2.0 has no feature for at all;
* spaces carry ``core:lodNSolid`` / ``core:lodNMultiSurface`` (no lod1
  MultiSurface, and LOD4 is gone);
* geometry is GML 3.2 and generic attributes are ``core:genericAttribute``
  wrapping ``gen:StringAttribute`` with *element* name/value.

The element names, namespaces and child order below are read from the CityGML
3.0 XSD bindings in ``citygml_parser.py`` (xsdata dataclasses), so they follow
the schema rather than being hand-typed.

Author:
    Taewook Kang (laputa99999@gmail.com)

Date:
    2026-09
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr

logger = logging.getLogger(__name__)

NS = {
    "core": "http://www.opengis.net/citygml/3.0",
    "bldg": "http://www.opengis.net/citygml/building/3.0",
    "con": "http://www.opengis.net/citygml/construction/3.0",
    "gen": "http://www.opengis.net/citygml/generics/3.0",
    "luse": "http://www.opengis.net/citygml/landuse/3.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

SCHEMA_LOCATION = " ".join([
    "http://www.opengis.net/citygml/3.0",
    "http://schemas.opengis.net/citygml/3.0/core.xsd",
    "http://www.opengis.net/citygml/building/3.0",
    "http://schemas.opengis.net/citygml/building/3.0/building.xsd",
    "http://www.opengis.net/citygml/construction/3.0",
    "http://schemas.opengis.net/citygml/construction/3.0/construction.xsd",
    "http://www.opengis.net/citygml/generics/3.0",
    "http://schemas.opengis.net/citygml/generics/3.0/generics.xsd",
    "http://www.opengis.net/citygml/landuse/3.0",
    "http://schemas.opengis.net/citygml/landuse/3.0/landUse.xsd",
])

# EM destination -> (role, feature element, containing property).
# The geometry property is chosen per element from its LoD and whether the mesh
# closes, so it is not part of the table.
PLACEMENT: Dict[str, Tuple[str, str, str]] = {
    "WallSurface": ("boundary", "con:WallSurface", "core:boundary"),
    "RoofSurface": ("boundary", "con:RoofSurface", "core:boundary"),
    "GroundSurface": ("boundary", "con:GroundSurface", "core:boundary"),
    "FloorSurface": ("boundary", "con:FloorSurface", "core:boundary"),
    "CeilingSurface": ("boundary", "con:CeilingSurface", "core:boundary"),
    "OuterFloorSurface": ("boundary", "con:OuterFloorSurface", "core:boundary"),
    "OuterCeilingSurface": ("boundary", "con:OuterCeilingSurface", "core:boundary"),
    "ClosureSurface": ("boundary", "core:ClosureSurface", "core:boundary"),
    # 3.0 splits the 2.0 opening into a thematic surface (WindowSurface, what
    # fills a wall) and a space (Window, the physical object); an IFC window
    # mapped from a wall opening is the surface
    "Window": ("opening", "con:WindowSurface", "con:fillingSurface"),
    "Door": ("opening", "con:DoorSurface", "con:fillingSurface"),
    "WindowSurface": ("opening", "con:WindowSurface", "con:fillingSurface"),
    "DoorSurface": ("opening", "con:DoorSurface", "con:fillingSurface"),
    "Room": ("room", "bldg:BuildingRoom", "bldg:buildingRoom"),
    "BuildingRoom": ("room", "bldg:BuildingRoom", "bldg:buildingRoom"),
    # 3.0 finally has a storey feature, so the LM/EM result can keep it
    "BuildingStorey": ("subdivision", "bldg:Storey", "bldg:buildingSubdivision"),
    "Storey": ("subdivision", "bldg:Storey", "bldg:buildingSubdivision"),
    "BuildingInstallation": ("installation", "bldg:BuildingInstallation",
                             "bldg:buildingInstallation"),
    "BuildingConstructiveElement": ("constructive", "bldg:BuildingConstructiveElement",
                                    "bldg:buildingConstructiveElement"),
    "BuildingPart": ("part", "bldg:BuildingPart", "bldg:buildingPart"),
    "LandUse": ("top", "luse:LandUse", "core:cityObjectMember"),
    "GenericCityObject": ("top", "gen:GenericOccupiedSpace", "core:cityObjectMember"),
    "GenericOccupiedSpace": ("top", "gen:GenericOccupiedSpace", "core:cityObjectMember"),
    "GenericThematicSurface": ("top", "gen:GenericThematicSurface", "core:cityObjectMember"),
}

# features that are spaces (lodNSolid / lodNMultiSurface, no lod1MultiSurface)
SPACE_ROLES = {"room", "subdivision", "installation", "constructive", "part"}
# thematic surfaces accept lod0..lod3 MultiSurface; WindowSurface/DoorSurface
# are thematic surfaces too, not spaces
SURFACE_ROLES = {"boundary", "opening"}

MAX_LOD = 3  # CityGML 3.0 dropped LOD4


def lod_level(name: Any, default: int = 2) -> int:
    """``"LOD2"`` -> ``2``; LOD4 is clamped since 3.0 has no LOD4."""
    text = str(name or "").upper().replace("LOD", "").strip()
    try:
        level = int(text)
    except ValueError:
        return default
    if level > MAX_LOD:
        logger.debug("CityGML 3.0 has no LOD%d; clamped to LOD%d", level, MAX_LOD)
        return MAX_LOD
    return max(0, level)


def is_closed_shell(geometry: Dict[str, Any]) -> bool:
    """True when every triangle edge is shared by exactly two faces.

    Only then may the mesh be written as a ``gml:Solid``; the LM ``extrude``
    operator produces such closed prisms, raw IFC triangulation usually does not.
    """
    faces = (geometry or {}).get("faces") or []
    if len(faces) < 12:  # fewer than four triangles cannot enclose a volume
        return False
    edges: Dict[Tuple[int, int], int] = {}
    for i in range(0, len(faces) - 2, 3):
        tri = faces[i], faces[i + 1], faces[i + 2]
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = (a, b) if a < b else (b, a)
            edges[key] = edges.get(key, 0) + 1
    return bool(edges) and all(count == 2 for count in edges.values())


def geometry_property(role: str, lod: Any, geometry: Dict[str, Any]) -> Tuple[str, bool]:
    """Pick the CityGML 3.0 geometry property; returns ``(name, as_solid)``."""
    level = lod_level(lod)
    if role in SURFACE_ROLES or role == "top":
        return f"core:lod{level}MultiSurface", False
    if is_closed_shell(geometry) and level >= 1:
        return f"core:lod{level}Solid", True
    # AbstractSpace has no lod1MultiSurface, so an open mesh moves up to LOD2
    if level == 1:
        level = 2
    return f"core:lod{level}MultiSurface", False


class Writer:
    """Writes the resolved (object, destination) pairs as CityGML 3.0."""

    def __init__(self, srs_name: Optional[str] = None):
        self.srs_name = srs_name
        self._used_ids: set = set()
        self._id_counts: Dict[str, int] = {}

    # -- ids ---------------------------------------------------------------
    def _id(self, value: str, prefix: str) -> str:
        """A gml:id unique within the document.

        Every polygon and ring needs one, so the suffix is tracked per base
        rather than rediscovered by scanning: the scan made this quadratic and
        cost about ten seconds on the sample.
        """
        import B2GM_GIS

        base = B2GM_GIS.gml_id(value, prefix=prefix)
        count = self._id_counts.get(base, 0) + 1
        candidate = base if count == 1 else f"{base}_{count}"
        while candidate in self._used_ids:
            count += 1
            candidate = f"{base}_{count}"
        self._id_counts[base] = count
        self._used_ids.add(candidate)
        return candidate

    # -- geometry ----------------------------------------------------------
    def _polygons(self, f, geom, indent):
        import B2GM_GIS

        verts, faces = B2GM_GIS._reshape(geom)
        for tri in faces:
            if len(tri) < 3:
                continue
            ring = list(tri) + [tri[0]]
            coords = " ".join(B2GM_GIS._fmt3(verts[i]) for i in ring if i < len(verts))
            f.write(f'{indent}<gml:surfaceMember>\n')
            f.write(f'{indent}  <gml:Polygon gml:id="{self._id("poly", "p")}">\n')
            f.write(f"{indent}    <gml:exterior>\n")
            f.write(f'{indent}      <gml:LinearRing gml:id="{self._id("ring", "r")}">\n')
            f.write(f'{indent}        <gml:posList srsDimension="3">{coords}</gml:posList>\n')
            f.write(f"{indent}      </gml:LinearRing>\n")
            f.write(f"{indent}    </gml:exterior>\n")
            f.write(f"{indent}  </gml:Polygon>\n")
            f.write(f"{indent}</gml:surfaceMember>\n")

    def _write_geometry(self, f, property_name, geom, indent, as_solid=False):
        if not geom:
            return
        srs = f" srsName={quoteattr(self.srs_name)}" if self.srs_name else ""
        f.write(f"{indent}<{property_name}>\n")
        if as_solid:
            f.write(f'{indent}  <gml:Solid gml:id="{self._id("solid", "sd")}"{srs}>\n')
            f.write(f"{indent}    <gml:exterior>\n")
            f.write(f'{indent}      <gml:Shell gml:id="{self._id("shell", "sh")}">\n')
            self._polygons(f, geom, f"{indent}        ")
            f.write(f"{indent}      </gml:Shell>\n")
            f.write(f"{indent}    </gml:exterior>\n")
            f.write(f"{indent}  </gml:Solid>\n")
        else:
            f.write(f'{indent}  <gml:MultiSurface gml:id="{self._id("ms", "m")}"{srs}>\n')
            self._polygons(f, geom, f"{indent}    ")
            f.write(f"{indent}  </gml:MultiSurface>\n")
        f.write(f"{indent}</{property_name}>\n")

    # -- attributes --------------------------------------------------------
    def _write_generic_attrs(self, f, obj, destination, indent):
        """core:genericAttribute -> gen:StringAttribute (name/value are elements)."""
        def attr(name, value):
            f.write(f"{indent}<core:genericAttribute>\n")
            f.write(f"{indent}  <gen:StringAttribute>\n")
            f.write(f"{indent}    <gen:name>{escape(str(name))}</gen:name>\n")
            f.write(f"{indent}    <gen:value>{escape(str(value))}</gen:value>\n")
            f.write(f"{indent}  </gen:StringAttribute>\n")
            f.write(f"{indent}</core:genericAttribute>\n")

        if obj.get("ifc_type"):
            attr("ifc_type", obj["ifc_type"])
        if obj.get("predefined_type"):
            attr("predefined_type", obj["predefined_type"])
        if obj.get("GUID"):
            attr("GUID", obj["GUID"])
        attr("gis_class", destination)
        if obj.get("_lod"):
            attr("lod", obj["_lod"])
        for pset_name, props in (obj.get("pset") or {}).items():
            for prop_name, prop_value in (props or {}).items():
                attr(f"{pset_name}.{prop_name}", prop_value)

    # -- features ----------------------------------------------------------
    def _write_feature(self, f, obj, destination, indent, placed_as=None,
                       children_writer=None):
        key = placed_as or destination
        role, element, container = PLACEMENT.get(key) or PLACEMENT["GenericCityObject"]
        geom = _geometry(obj)
        property_name, as_solid = geometry_property(role, obj.get("_lod"), geom)

        f.write(f"{indent}<{container}>\n")
        f.write(f'{indent}  <{element} gml:id="{self._id(obj.get("GUID") or destination, "f")}">\n')
        f.write(f"{indent}    <gml:name>{escape(str(obj.get('name', destination)))}</gml:name>\n")
        self._write_generic_attrs(f, obj, destination, f"{indent}    ")
        # AbstractSpace orders core:boundary before the lod geometry
        if children_writer is not None:
            children_writer("boundary", f, f"{indent}    ")
        self._write_geometry(f, property_name, geom, f"{indent}    ", as_solid)
        if children_writer is not None:
            children_writer("after", f, f"{indent}    ")
        f.write(f"{indent}  </{element}>\n")
        f.write(f"{indent}</{container}>\n")
        return 1

    def _write_boundary(self, f, obj, destination, openings, indent) -> int:
        _role, element, container = PLACEMENT[destination]
        geom = _geometry(obj)
        level = lod_level(obj.get("_lod"))
        if openings:
            level = max(level, 3)  # con:fillingSurface needs LOD3
        f.write(f"{indent}<{container}>\n")
        f.write(f'{indent}  <{element} gml:id="{self._id(obj.get("GUID") or destination, "s")}">\n')
        f.write(f"{indent}    <gml:name>{escape(str(obj.get('name', destination)))}</gml:name>\n")
        self._write_generic_attrs(f, obj, destination, f"{indent}    ")
        self._write_geometry(f, f"core:lod{level}MultiSurface", geom, f"{indent}    ")
        written = 1
        for opening, opening_destination in openings:
            written += self._write_feature(f, opening, opening_destination, f"{indent}    ")
        f.write(f"{indent}  </{element}>\n")
        f.write(f"{indent}</{container}>\n")
        return written


def _geometry(obj):
    import B2GM_GIS

    return B2GM_GIS.element_geometry(obj)


def storey_contents(resolved) -> Dict[str, str]:
    """Map an element GUID to the GUID of the storey that contains it.

    IFC records ``storey -contains-> element`` (IfcRelContainedInSpatialStructure)
    and ``storey -aggregates-> element``; CityGML 3.0 can hold that hierarchy
    because a ``bldg:Storey`` carries its own rooms, installations and boundaries.
    """
    inside: Dict[str, str] = {}
    for obj, destination in resolved:
        if (PLACEMENT.get(destination) or ("",))[0] != "subdivision":
            continue
        storey_guid = obj.get("GUID")
        if not storey_guid:
            continue
        for rel in obj.get("relationship") or []:
            if rel.get("name") in ("contains", "aggregates"):
                guid = (rel.get("related") or {}).get("guid")
                if guid:
                    inside[guid] = storey_guid
    return inside


def _empty_bucket() -> Dict[str, list]:
    return {"boundary": [], "constructive": [], "installation": [], "room": [], "part": []}


def store(fname: str, resolved: List[Tuple[Dict[str, Any], str]],
          srs_name: Optional[str] = None, nest_by_storey: bool = True) -> int:
    """Write the resolved elements as a CityGML 3.0 document.

    With ``nest_by_storey`` the IFC spatial hierarchy is kept: elements a storey
    contains are written inside that ``bldg:Storey`` instead of flat under the
    building.
    """
    import B2GM_GIS

    writer = Writer(srs_name)
    building_obj = next((o for o, d in resolved if d in B2GM_GIS.BUILDING_DESTINATIONS), None)
    hosts = B2GM_GIS.GIS._opening_hosts(resolved)
    inside = storey_contents(resolved) if nest_by_storey else {}

    storeys: List[Tuple[Dict[str, Any], str]] = []
    openings: Dict[str, List[Tuple[Dict[str, Any], str]]] = {}
    loose_openings: List[Tuple[Dict[str, Any], str]] = []
    top: List[Tuple[Dict[str, Any], str]] = []
    # buckets are keyed by container: None is the building, else a storey GUID
    buckets: Dict[Optional[str], Dict[str, list]] = {None: _empty_bucket()}

    for obj, destination in resolved:
        if obj is building_obj:
            continue
        role = (PLACEMENT.get(destination) or ("", "", ""))[0]
        if role == "subdivision":
            storeys.append((obj, destination))
            continue
        if role == "top":
            top.append((obj, destination))
            continue
        if not _geometry(obj):
            continue
        if role == "opening":
            host = hosts.get(obj.get("GUID", ""))
            (openings.setdefault(host, []) if host else loose_openings).append(
                (obj, destination))
            continue
        if role not in _empty_bucket():
            top.append((obj, destination))
            continue
        container = inside.get(obj.get("GUID", ""))
        buckets.setdefault(container, _empty_bucket())[role].append((obj, destination))

    # a storey that contains nothing we kept still gets written, just empty
    for obj, _ in storeys:
        buckets.setdefault(obj.get("GUID"), _empty_bucket())

    def write_boundaries(f, bucket, indent) -> int:
        count = 0
        for obj, destination in bucket["boundary"]:
            count += writer._write_boundary(
                f, obj, destination, openings.get(obj.get("GUID", ""), []), indent)
        return count

    def write_contents(f, bucket, indent) -> int:
        """constructive -> installation -> room, per the 3.0 element order."""
        count = 0
        for role in ("constructive", "installation", "room", "part"):
            for obj, destination in bucket[role]:
                count += writer._write_feature(f, obj, destination, indent)
        return count

    lower, upper = B2GM_GIS.GIS._envelope(resolved)
    written = 1
    building_bucket = buckets[None]

    with open(fname, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<core:CityModel")
        for prefix, uri in NS.items():
            f.write(f'\n    xmlns:{prefix}="{uri}"')
        f.write(f"\n    xsi:schemaLocation={quoteattr(SCHEMA_LOCATION)}")
        f.write(">\n")

        srs = f" srsName={quoteattr(srs_name)}" if srs_name else ""
        f.write("  <gml:boundedBy>\n")
        f.write(f'    <gml:Envelope{srs} srsDimension="3">\n')
        f.write(f"      <gml:lowerCorner>{B2GM_GIS._fmt3(lower)}</gml:lowerCorner>\n")
        f.write(f"      <gml:upperCorner>{B2GM_GIS._fmt3(upper)}</gml:upperCorner>\n")
        f.write("    </gml:Envelope>\n")
        f.write("  </gml:boundedBy>\n")

        b_name = (building_obj or {}).get("name", "Building")
        b_guid = (building_obj or {}).get("GUID") or "building_1"
        f.write("  <core:cityObjectMember>\n")
        f.write(f'    <bldg:Building gml:id="{writer._id(b_guid, "bldg")}">\n')
        f.write(f"      <gml:name>{escape(str(b_name))}</gml:name>\n")
        if building_obj is not None:
            writer._write_generic_attrs(f, building_obj, "CityModel.Building", "      ")

        # AbstractBuildingType order: boundary, geometry, constructive element,
        # installation, room, subdivision
        written += write_boundaries(f, building_bucket, "      ")
        if building_obj is not None:
            geom = _geometry(building_obj)
            if geom:
                name, as_solid = geometry_property("building", building_obj.get("_lod"), geom)
                writer._write_geometry(f, name, geom, "      ", as_solid)
        for obj, destination in loose_openings:
            # nothing to fill: keep it as an installation rather than drop it
            written += writer._write_feature(f, obj, destination, "      ",
                                             placed_as="BuildingInstallation")
        written += write_contents(f, building_bucket, "      ")

        for obj, destination in storeys:
            bucket = buckets[obj.get("GUID")]

            def children(where, out, indent, bucket=bucket):
                # StoreyType orders core:boundary before its own geometry, then
                # buildingConstructiveElement / buildingInstallation / buildingRoom
                return (write_boundaries(out, bucket, indent) if where == "boundary"
                        else write_contents(out, bucket, indent))

            written += writer._write_feature(f, obj, destination, "      ",
                                             children_writer=children)
            written += sum(len(bucket[role]) for role in bucket)

        f.write("    </bldg:Building>\n")
        f.write("  </core:cityObjectMember>\n")

        for obj, destination in top:
            role, element, _container = PLACEMENT.get(destination) or PLACEMENT["GenericCityObject"]
            geom = _geometry(obj)
            f.write("  <core:cityObjectMember>\n")
            f.write(f'    <{element} gml:id="{writer._id(obj.get("GUID") or destination, "o")}">\n')
            f.write(f"      <gml:name>{escape(str(obj.get('name', destination)))}</gml:name>\n")
            writer._write_generic_attrs(f, obj, destination, "      ")
            if geom:
                name, as_solid = geometry_property(role, obj.get("_lod"), geom)
                writer._write_geometry(f, name, geom, "      ", as_solid)
            f.write(f"    </{element}>\n")
            f.write("  </core:cityObjectMember>\n")
            written += 1

        f.write("</core:CityModel>\n")
    return written
