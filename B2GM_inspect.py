"""
B2GM inspect - object trees and properties for the web view's lower right panel.

An IFC opens as its spatial structure (project, site, building, storeys and the
elements they contain), with attributes and property sets read per object on
request, since a large model has more of them than a browser wants in one go.
A CityGML file opens as its feature tree (buildings, boundary surfaces,
openings, rooms) with each feature's attributes inline.  Any other file or a
folder gets a short metadata table.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Optional, Tuple

GML_NS = ("http://www.opengis.net/gml", "http://www.opengis.net/gml/3.2")
RUN_RECORD = "b2gm_run.json"

# property groups are [title, [[key, value], ...]] so the order survives JSON
Groups = List[List[Any]]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _when(seconds: float) -> str:
    return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


# ---------------------------------------------------------------------------
# a small cache: the tree and the per-object requests that follow it should
# not reopen a 20 MB file each time
# ---------------------------------------------------------------------------
_CACHE: "OrderedDict[Tuple[str, float, str], Any]" = OrderedDict()
_LOCK = threading.Lock()


def _cached(path: str, kind: str, load):
    key = (os.path.abspath(path), os.path.getmtime(path), kind)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    value = load(path)
    with _LOCK:
        _CACHE[key] = value
        while len(_CACHE) > 4:
            _CACHE.popitem(last=False)
    return value


# ---------------------------------------------------------------------------
# IFC
# ---------------------------------------------------------------------------
def _ifc_node(entity) -> Dict[str, Any]:
    name = getattr(entity, "Name", None) or ""
    return {"id": getattr(entity, "GlobalId", None) or f"#{entity.id()}",
            "step": entity.id(), "cls": entity.is_a(), "name": name, "children": []}


def _ifc_children(entity) -> List[Any]:
    out = []
    for rel in getattr(entity, "IsDecomposedBy", None) or ():
        out.extend(rel.RelatedObjects)
    for rel in getattr(entity, "ContainsElements", None) or ():
        out.extend(rel.RelatedElements)
    return out


def inspect_ifc(path: str) -> Dict[str, Any]:
    ifc = _cached(path, "ifc", _open_ifc)
    seen = set()

    def build(entity, depth=0):
        node = _ifc_node(entity)
        seen.add(entity.id())
        if depth < 32:
            for child in _ifc_children(entity):
                if child.id() not in seen:
                    node["children"].append(build(child, depth + 1))
        return node

    roots = [build(project) for project in ifc.by_type("IfcProject")]
    # products outside the spatial structure would otherwise be invisible here
    loose = [p for p in ifc.by_type("IfcProduct")
             if p.id() not in seen and not p.is_a("IfcOpeningElement")
             and not p.is_a("IfcAnnotation")]
    if loose:
        roots.append({"id": "", "step": None, "cls": "", "name": "(not in the spatial structure)",
                      "children": [build(p) for p in loose if p.id() not in seen]})
    counts = Counter(p.is_a() for p in ifc.by_type("IfcProduct"))
    return {"kind": "ifc", "schema": ifc.schema, "tree": roots,
            "summary": [["schema", ifc.schema],
                        ["products", sum(counts.values())],
                        ["types", ", ".join(f"{k} {v}" for k, v in counts.most_common(6))]]}


def _open_ifc(path: str):
    import ifcopenshell
    return ifcopenshell.open(path)


def _ifc_value(value) -> Any:
    if hasattr(value, "is_a"):
        if hasattr(value, "wrappedValue"):
            return value.wrappedValue
        label = getattr(value, "Name", None)
        return f"#{value.id()} {value.is_a()}" + (f" {label}" if label else "")
    if isinstance(value, (tuple, list)):
        if len(value) > 6:
            return f"{len(value)} items"
        return ", ".join(str(_ifc_value(v)) for v in value)
    return value


def ifc_properties(path: str, step: int) -> Groups:
    import ifcopenshell.util.element as util

    ifc = _cached(path, "ifc", _open_ifc)
    entity = ifc.by_id(int(step))
    attributes = []
    for name, value in entity.get_info(recursive=False).items():
        if name in ("id", "type") or value is None:
            continue
        if name in ("OwnerHistory", "ObjectPlacement", "Representation"):
            continue
        attributes.append([name, _ifc_value(value)])
    groups: Groups = [["IFC " + entity.is_a(), [["STEP id", f"#{entity.id()}"]] + attributes]]

    related = []
    container = util.get_container(entity) if entity.is_a("IfcElement") else None
    if container is not None:
        related.append(["container", f"{container.is_a()} {container.Name or ''}".strip()])
    element_type = util.get_type(entity)
    if element_type is not None:
        related.append(["type", f"{element_type.is_a()} {element_type.Name or ''}".strip()])
    material = util.get_material(entity)
    if material is not None:
        related.append(["material", getattr(material, "Name", None) or material.is_a()])
    if related:
        groups.append(["Relations", related])

    for pset, values in sorted(util.get_psets(entity).items()):
        items = [[k, _ifc_value(v)] for k, v in values.items() if k != "id"]
        if items:
            groups.append([pset, items])
    return groups


# ---------------------------------------------------------------------------
# CityGML
# ---------------------------------------------------------------------------
# wrappers that only carry geometry; a feature's tree stops at them
GEOMETRY_PREFIXES = ("lod0", "lod1", "lod2", "lod3", "lod4")


def _is_feature(element) -> bool:
    return (_ns(element.tag) not in GML_NS
            and any(k.endswith("}id") and _ns(k) in GML_NS for k in element.attrib))


def _gml_id(element) -> str:
    for key, value in element.attrib.items():
        if key.endswith("}id"):
            return value
    return ""


def _citygml_props(element) -> Tuple[str, Groups, int]:
    name = ""
    general: List[List[Any]] = [["class", _local(element.tag)], ["gml:id", _gml_id(element)]]
    psets: "OrderedDict[str, List[List[Any]]]" = OrderedDict()
    geometry: Counter = Counter()
    polygons = 0
    for child in element:
        local = _local(child.tag)
        if _ns(child.tag) in GML_NS:
            if local == "name" and not name:
                name = (child.text or "").strip()
                general.append(["gml:name", name])
            elif local == "description":
                general.append(["gml:description", (child.text or "").strip()])
            continue
        if local in ("stringAttribute", "intAttribute", "doubleAttribute",
                     "StringAttribute", "IntAttribute", "DoubleAttribute",
                     "genericAttribute"):
            target = child
            if local == "genericAttribute" and len(child):
                target = child[0]
            key = target.get("name") or next(
                (c.text for c in target if _local(c.tag) == "name"), "") or ""
            value = next((c.text for c in target if _local(c.tag) == "value"), "") or ""
            group, _, short = key.partition(".") if "." in key else ("Attributes", "", key)
            psets.setdefault(group, []).append([short, value.strip()])
            continue
        if local.startswith(GEOMETRY_PREFIXES):
            count = sum(1 for e in child.iter() if _local(e.tag) == "Polygon")
            geometry[local] += count
            polygons += count
            continue
        if len(child) == 0 and (child.text or "").strip():
            general.append([local, child.text.strip()])
    groups: Groups = [["Feature", general]]
    groups.extend([group, items] for group, items in psets.items())
    if geometry:
        groups.append(["Geometry", [[k, f"{v} polygons"] for k, v in geometry.items()]])
    return name, groups, polygons


def _citygml_tree(element, depth=0) -> List[Dict[str, Any]]:
    """Feature nodes under ``element``, looking through property wrappers."""
    nodes = []
    for child in element:
        if _ns(child.tag) in GML_NS or _local(child.tag).startswith(GEOMETRY_PREFIXES):
            continue
        if _is_feature(child):
            name, groups, polygons = _citygml_props(child)
            nodes.append({"id": _gml_id(child), "cls": _local(child.tag), "name": name,
                          "props": groups,
                          "children": _citygml_tree(child, depth + 1) if depth < 16 else []})
        elif len(child):
            nodes.extend(_citygml_tree(child, depth))
    return nodes


def _load_citygml(path: str) -> Dict[str, Any]:
    root = ET.parse(path).getroot()
    version = "3.0" if "/3.0" in _ns(root.tag) else "2.0"
    srs = next((e.get("srsName") for e in root.iter() if e.get("srsName")), None)
    tree = _citygml_tree(root)
    counts: Counter = Counter()

    def tally(nodes):
        for node in nodes:
            counts[node["cls"]] += 1
            tally(node["children"])
    tally(tree)
    return {"kind": "citygml", "tree": tree,
            "summary": [["CityGML", version], ["CRS", srs or "-"],
                        ["city objects", len(tree)],
                        ["features", sum(counts.values())],
                        ["classes", ", ".join(f"{k} {v}" for k, v in counts.most_common(6))]]}


def inspect_citygml(path: str) -> Dict[str, Any]:
    return _cached(path, "gml", _load_citygml)


# ---------------------------------------------------------------------------
# anything else: metadata
# ---------------------------------------------------------------------------
def _json_summary(path: str) -> Groups:
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, ValueError) as exc:
        return [["JSON", [["error", str(exc)]]]]
    if os.path.basename(path) == RUN_RECORD and isinstance(document, dict):
        stages = [[s.get("type", ""), s.get("output", "")] for s in document.get("stages", [])]
        head = [[k, document[k]] for k in ("input", "pipeline", "citygml_version", "final_output")
                if k in document]
        return [["Pipeline run", head], ["Stages", stages]]
    items = []
    if isinstance(document, dict):
        for key, value in list(document.items())[:40]:
            if isinstance(value, dict):
                value = f"object, {len(value)} keys"
            elif isinstance(value, list):
                value = f"array, {len(value)} items"
            items.append([key, value])
        return [["JSON object", items]]
    if isinstance(document, list):
        return [["JSON array", [["items", len(document)]]]]
    return [["JSON", [["value", document]]]]


def _folder_meta(path: str) -> Groups:
    files = dirs = total = 0
    latest = 0.0
    kinds: Counter = Counter()
    for base, subdirs, names in os.walk(path):
        subdirs[:] = [d for d in subdirs if not d.startswith(".") and d != "__pycache__"]
        dirs += len(subdirs)
        for name in names:
            if name.startswith("."):
                continue
            stat = os.stat(os.path.join(base, name))
            files += 1
            total += stat.st_size
            latest = max(latest, stat.st_mtime)
            kinds[os.path.splitext(name)[1].lower() or "(none)"] += 1
    groups: Groups = [["Folder", [["name", os.path.basename(path) or path],
                                  ["files", files], ["folders", dirs],
                                  ["total size", _size(total)],
                                  ["last change", _when(latest) if latest else "-"]]]]
    if kinds:
        groups.append(["File types", [[k, v] for k, v in kinds.most_common()]])
    record = os.path.join(path, RUN_RECORD)
    if os.path.isfile(record):
        groups.extend(_json_summary(record))
    return groups


def _file_meta(path: str) -> Groups:
    stat = os.stat(path)
    suffix = os.path.splitext(path)[1].lower()
    head = [["name", os.path.basename(path)], ["type", suffix.lstrip(".") or "-"],
            ["size", f"{_size(stat.st_size)} ({stat.st_size} bytes)"],
            ["modified", _when(stat.st_mtime)]]
    groups: Groups = [["File", head]]
    if suffix == ".json":
        groups.extend(_json_summary(path))
    elif suffix in (".txt", ".md", ".csv", ".xml", ".obj", ".geojson") and stat.st_size < 50_000_000:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = sum(1 for _ in f)
        head.append(["lines", lines])
    return groups


def inspect_path(path: str) -> Dict[str, Any]:
    """What the lower right panel shows for ``path``."""
    if os.path.isdir(path):
        return {"kind": "folder", "meta": _folder_meta(path)}
    suffix = os.path.splitext(path)[1].lower()
    meta = _file_meta(path)
    if suffix == ".ifc":
        result = inspect_ifc(path)
    elif suffix == ".gml":
        result = inspect_citygml(path)
    else:
        return {"kind": "file", "meta": meta}
    result["meta"] = meta
    return result


def node_properties(path: str, step: Optional[str]) -> Groups:
    if step is None or not path.lower().endswith(".ifc"):
        return []
    return ifc_properties(path, int(step))
