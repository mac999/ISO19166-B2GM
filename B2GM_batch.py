"""
B2GM batch - run one mapping per building folder and merge the results.

A district is a folder of building folders::

    input_data/teheran-ro/
        01_seolleung_block/   pipeline.json   (+ optional model.ifc)
        02_seolleung_lod2/    pipeline.json
        ...

Each building folder holds the pipeline JSON that maps that building, so the
PD / CM / EM / LM choices can differ from one building to the next.  The IFC
is either a file in the folder or named by the pipeline's top-level ``input``
key, relative to the folder, so one sample model can be placed many times
without being copied.  Every building is written under ``<output>/<folder>/``
and the final CityGML files are merged into one city model named after the
district folder.

Author:
    Taewook Kang (laputa99999@gmail.com)
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PIPELINE_KEY = "BIM_GIS_mapping.pipeline"
GML_ID = "{http://www.opengis.net/gml}id"
GML32_ID = "{http://www.opengis.net/gml/3.2}id"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def _pipeline_in(folder: str) -> Optional[str]:
    """The first JSON in ``folder`` that holds a pipeline."""
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as f:
                document = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and PIPELINE_KEY in document:
            return path
    return None


def _ifc_for(folder: str, pipeline: str) -> Optional[str]:
    """The IFC a building folder maps: the pipeline's ``input`` or the folder's own .ifc."""
    with open(pipeline, encoding="utf-8") as f:
        document = json.load(f)
    named = document.get("input")
    if named:
        path = named if os.path.isabs(named) else os.path.normpath(os.path.join(folder, named))
        return path if os.path.isfile(path) else None
    ifcs = sorted(n for n in os.listdir(folder) if n.lower().endswith(".ifc"))
    return os.path.join(folder, ifcs[0]) if ifcs else None


def discover(folder: str) -> List[Dict[str, str]]:
    """List the building folders under ``folder`` that can be run."""
    entries = []
    for name in sorted(os.listdir(folder)):
        sub = os.path.join(folder, name)
        if not os.path.isdir(sub):
            continue
        pipeline = _pipeline_in(sub)
        if not pipeline:
            logger.info("%s: no pipeline, skipped", name)
            continue
        ifc = _ifc_for(sub, pipeline)
        if not ifc:
            logger.warning("%s: no ifc to map, skipped", name)
            continue
        entries.append({"name": name, "folder": sub, "pipeline": pipeline, "ifc": ifc})
    return entries


def run_folder(folder: str, output_dir: str, citygml_version: Optional[str] = None,
               save_json: bool = False) -> Dict[str, Any]:
    """Map every building folder under ``folder`` and merge the results."""
    import B2GM_main

    folder = os.path.abspath(folder)
    entries = discover(folder)
    if not entries:
        logger.error("%s: nothing to run", folder)
        return {"entries": [], "merged": None}
    logger.info("%s: %d buildings", os.path.basename(folder), len(entries))

    finals = []
    for index, entry in enumerate(entries, 1):
        out = os.path.join(output_dir, entry["name"])
        logger.info("[%d/%d] %s <- %s", index, len(entries), entry["name"],
                    os.path.basename(entry["ifc"]))
        context = B2GM_main.mapping_ifc_to_target(
            entry["ifc"], "city.gml", entry["pipeline"], out, citygml_version)
        if save_json:
            B2GM_main.save_models(context, out)
        entry["output"] = context.get("final_output")
        entry["srs_name"] = context.get("srs_name")
        if entry["output"] and os.path.isfile(entry["output"]):
            finals.append((entry["name"], entry["output"]))

    merged = None
    if finals:
        merged = os.path.join(output_dir, os.path.basename(folder) + ".gml")
        try:
            count = merge_citygml(finals, merged)
            logger.info("merged %d buildings -> %s", count, merged)
        except ValueError as exc:
            logger.error("merge skipped: %s", exc)
            merged = None
    return {"entries": entries, "merged": merged}


def _ncname(name: str) -> str:
    """A gml:id prefix that keeps the id a valid NCName whatever the folder is called."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return cleaned if re.match(r"[A-Za-z_]", cleaned) else "b_" + cleaned


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def merge_citygml(named_paths: List, out_path: str) -> int:
    """Write one CityModel holding every cityObjectMember of ``named_paths``.

    ``named_paths`` is ``[(name, path), ...]``; each name prefixes the gml:ids
    of its file so the same model placed twice does not collide.  All files
    must be the same CityGML version; the first one's root attributes and CRS
    are kept and the envelope is recomputed over everything.  Returns the
    number of members written.
    """
    import B2GM_GIS
    import B2GM_citygml3

    roots = []
    for name, path in named_paths:
        roots.append((name, ET.parse(path).getroot()))
    core_uri = roots[0][1].tag.split("}")[0].strip("{")
    for name, root in roots[1:]:
        if root.tag.split("}")[0].strip("{") != core_uri:
            raise ValueError(f"{name} is a different CityGML version from the first building")
    is_3 = core_uri == B2GM_citygml3.NS["core"]
    ns = B2GM_citygml3.NS if is_3 else B2GM_GIS.NS
    for prefix, uri in ns.items():
        ET.register_namespace(prefix, uri)
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    gml = ns["gml"]
    id_attr = GML32_ID if is_3 else GML_ID

    first = roots[0][1]
    merged = ET.Element(first.tag, dict(first.attrib))
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    srs = None
    count = 0
    for name, root in roots:
        envelope = root.find(f"{{{gml}}}boundedBy/{{{gml}}}Envelope")
        if envelope is not None and srs is None:
            srs = envelope.get("srsName")
        prefix = _ncname(name) + "_"
        for member in root:
            if _local(member.tag) != "cityObjectMember":
                continue
            clone = copy.deepcopy(member)
            for element in clone.iter():
                if id_attr in element.attrib:
                    element.set(id_attr, prefix + element.get(id_attr))
                href = element.get(XLINK_HREF)
                if href and href.startswith("#"):
                    element.set(XLINK_HREF, "#" + prefix + href[1:])
                if _local(element.tag) in ("posList", "pos") and element.text:
                    numbers = [float(v) for v in element.text.split()]
                    for i in range(0, len(numbers) - 2, 3):
                        for axis in range(3):
                            lo[axis] = min(lo[axis], numbers[i + axis])
                            hi[axis] = max(hi[axis], numbers[i + axis])
            merged.append(clone)
            count += 1

    if count and lo[0] != float("inf"):
        bounded = ET.Element(f"{{{gml}}}boundedBy")
        envelope = ET.SubElement(bounded, f"{{{gml}}}Envelope", {"srsDimension": "3"})
        if srs:
            envelope.set("srsName", srs)
        ET.SubElement(envelope, f"{{{gml}}}lowerCorner").text = B2GM_GIS._fmt3(lo)
        ET.SubElement(envelope, f"{{{gml}}}upperCorner").text = B2GM_GIS._fmt3(hi)
        merged.insert(0, bounded)

    ET.indent(merged, space="  ")
    ET.ElementTree(merged).write(out_path, encoding="UTF-8", xml_declaration=True)
    return count
