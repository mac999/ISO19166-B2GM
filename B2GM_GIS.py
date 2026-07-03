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
    "gml": "http://www.opengis.net/gml",
}

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

# destinations that identify the building itself (not a sub-feature).
BUILDING_DESTINATIONS = {"CityModel.Building", "Building", "bldg:Building"}

# keys that are internal book-keeping rather than payload properties
_META_KEYS = {"pset", "ifc_type", "geometry", "_destination", "_lod", "_pset_operation"}


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
    def store(self, fname: str, objects: List[Dict[str, Any]], stage: Dict[str, Any]) -> int:
        """Write ``objects`` (matching the EM rules of ``stage``) as CityGML 2.0.

        Returns the number of features written (building + sub-features).
        """
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

        lower, upper = self._envelope(resolved)

        with open(fname, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write("<core:CityModel")
            for prefix, uri in NS.items():
                f.write(f'\n    xmlns:{prefix}="{uri}"')
            f.write(">\n")

            f.write("  <gml:boundedBy>\n")
            f.write('    <gml:Envelope srsDimension="3">\n')
            f.write(f'      <gml:lowerCorner>{_fmt3(lower)}</gml:lowerCorner>\n')
            f.write(f'      <gml:upperCorner>{_fmt3(upper)}</gml:upperCorner>\n')
            f.write("    </gml:Envelope>\n")
            f.write("  </gml:boundedBy>\n")

            written = self._write_building(f, resolved)

            f.write("</core:CityModel>\n")
        return written

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _envelope(resolved) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        seen = False
        for obj, _ in resolved:
            geom = obj.get("geometry")
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

    def _write_building(self, f, resolved) -> int:
        # pick the building element (if any) to carry the building identity
        building_obj = next((o for o, d in resolved if d in BUILDING_DESTINATIONS), None)
        b_guid = (building_obj or {}).get("GUID") if building_obj else None
        b_name = (building_obj or {}).get("name", "Building") if building_obj else "Building"
        b_id = gml_id(b_guid or "building_1", prefix="bldg")

        f.write("  <core:cityObjectMember>\n")
        f.write(f'    <bldg:Building gml:id="{b_id}">\n')
        f.write(f"      <gml:name>{escape(str(b_name))}</gml:name>\n")
        written = 1

        if building_obj is not None:
            self._write_generic_attrs(f, building_obj, "CityModel.Building", indent="      ")

        for obj, destination in resolved:
            if obj is building_obj:
                continue
            geom = obj.get("geometry")
            if geom and destination in BOUNDARY_SURFACES:
                self._write_boundary_surface(f, obj, destination, geom)
                written += 1
            elif geom:
                self._write_installation(f, obj, destination, geom)
                written += 1
            else:
                # no geometry: keep the element discoverable on the building
                self._write_generic_attrs(f, obj, destination, indent="      ")

        f.write("    </bldg:Building>\n")
        f.write("  </core:cityObjectMember>\n")
        return written

    def _write_boundary_surface(self, f, obj, destination, geom):
        surf_id = gml_id(obj.get("GUID") or destination, prefix="s")
        f.write("      <bldg:boundedBy>\n")
        f.write(f'        <bldg:{destination} gml:id="{surf_id}">\n')
        f.write(f"          <gml:name>{escape(str(obj.get('name', destination)))}</gml:name>\n")
        self._write_generic_attrs(f, obj, destination, indent="          ")
        f.write("          <bldg:lod2MultiSurface>\n")
        self._write_multisurface(f, geom, indent="            ")
        f.write("          </bldg:lod2MultiSurface>\n")
        f.write(f"        </bldg:{destination}>\n")
        f.write("      </bldg:boundedBy>\n")

    def _write_installation(self, f, obj, destination, geom):
        inst_id = gml_id(obj.get("GUID") or destination, prefix="i")
        f.write("      <bldg:outerBuildingInstallation>\n")
        f.write(f'        <bldg:BuildingInstallation gml:id="{inst_id}">\n')
        f.write(f"          <gml:name>{escape(str(obj.get('name', destination)))}</gml:name>\n")
        # record the intended CityGML class (e.g. Window/Door/Room) as an attribute
        self._write_generic_attrs(f, obj, destination, indent="          ")
        f.write("          <bldg:lod2Geometry>\n")
        self._write_multisurface(f, geom, indent="            ")
        f.write("          </bldg:lod2Geometry>\n")
        f.write("        </bldg:BuildingInstallation>\n")
        f.write("      </bldg:outerBuildingInstallation>\n")

    @staticmethod
    def _write_multisurface(f, geom, indent="  "):
        verts, faces = _reshape(geom)
        f.write(f"{indent}<gml:MultiSurface>\n")
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
