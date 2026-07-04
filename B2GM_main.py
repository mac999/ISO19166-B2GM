"""
B2GM main - ISO 19166 BIM-to-GIS conceptual mapping pipeline.

Runs an IFC (BIM) file through the four B2GM mapping stages defined in a
pipeline file (see ``B2GM_example.json``):

    PD  Perspective Definition  - select the required BIM subset
    CM  Coordinate Mapping      - source CRS -> destination CRS
    EM  Element Mapping         - IFC element -> GIS/CityGML element
    LM  LoD Mapping             - assign a GIS Level-of-Detail

Stages share a ``context`` dict so element mapping (EM) can hand its result to
LoD mapping (LM) without re-parsing intermediate files.  Each stage also writes
its output file for inspection.

Conventions:
    Input data and the mapping/pipeline config live under ``input_data/`` and
    all results are written under ``output/``.  Both are the CLI defaults, so a
    bare ``python B2GM_main.py`` runs the shipped example end to end.

Usage:
    python B2GM_main.py
    python B2GM_main.py --input input_data/duplex_apartment.ifc \
                        --pipeline input_data/B2GM_example.json \
                        --output-dir output

Author:
    Taewook Kang (laputa99999@gmail.com)

Date:
    2024-01-02 (completed 2026-07)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from typing import Any, Dict, List

import B2GM_BIM
import B2GM_CM
import B2GM_element
import B2GM_GIS
import B2GM_LM
import B2GM_PD

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _write_sidecar(output_file: str, suffix: str, data: Dict[str, Any]):
    path = f"{output_file}.{suffix}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    except Exception as exc:  # pragma: no cover - non fatal
        logger.warning("could not write sidecar %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------
def mapping_PD(input_file: str, output_file: str, stage: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Perspective Definition: select the required BIM subset from the source."""
    logger.info("Stage PD, input: %s, output: %s", input_file, output_file)
    if not os.path.exists(input_file):
        logger.error("Input file does not exist: %s", input_file)
        return input_file

    objects = context.get("objects")
    if objects is None:
        objects = B2GM_BIM.BIM().parse(input_file)
        context["objects"] = objects

    perspective = B2GM_PD.PerspectiveDefinition.from_stage(stage)
    selected = perspective.select(objects)
    context["perspective"] = perspective
    context["perspective_guids"] = {o.get("GUID") for o in selected if o.get("GUID")}

    logger.info("PD selected %d / %d elements", len(selected), len(objects))
    _write_sidecar(
        output_file,
        "pd",
        {
            "logic_view": perspective.logic_view,
            "selected": [{"name": o.get("name"), "ifc_type": o.get("ifc_type"), "GUID": o.get("GUID")} for o in selected],
        },
    )

    # keep a valid IFC flowing to the next stage
    if os.path.abspath(input_file) != os.path.abspath(output_file):
        shutil.copy(input_file, output_file)
    return output_file


def mapping_CM(input_file: str, output_file: str, stage: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Coordinate Mapping: compute the destination-CRS georeferencing."""
    logger.info("Stage CM, input: %s, output: %s", input_file, output_file)
    if not os.path.exists(input_file):
        logger.error("Input file does not exist: %s", input_file)
        return input_file

    mapping = B2GM_CM.CoordinateMapping.from_stage(stage)
    summary: Dict[str, Any] = {"source_crs": mapping.source_crs, "dest_crs": mapping.dest_crs}
    try:
        import ifcopenshell

        ifc = ifcopenshell.open(input_file)
        summary = B2GM_CM.apply_to_ifc(ifc, mapping)
    except Exception as exc:
        logger.warning("CM could not read IFC georeferencing: %s", exc)
    context["crs"] = summary
    logger.info("CM %s -> %s, origin: %s", summary.get("source_crs"), summary.get("dest_crs"), summary.get("dest_origin"))
    _write_sidecar(output_file, "cm", summary)

    if os.path.abspath(input_file) != os.path.abspath(output_file):
        shutil.copy(input_file, output_file)
    return output_file


def mapping_EM(input_file: str, output_file: str, stage: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Element Mapping: IFC elements -> GIS/CityGML elements."""
    logger.info("Stage EM, input: %s, output: %s", input_file, output_file)

    objects = context.get("objects")
    if objects is None or not context.get("objects_from", "").startswith(input_file):
        objects = B2GM_BIM.BIM().parse(input_file)
        context["objects"] = objects
        context["objects_from"] = input_file

    # restrict to the PD perspective when one was defined
    guids = context.get("perspective_guids")
    if guids:
        objects = [o for o in objects if o.get("GUID") in guids] or objects

    rules = B2GM_element.rules_from_stage(stage)
    mapped = B2GM_element.apply(objects, rules)
    context["em_rules"] = rules
    context["em_mapped"] = mapped
    logger.info("EM mapped %d / %d elements", len(mapped), len(objects))

    B2GM_GIS.GIS().store(output_file, objects, stage)
    return output_file


def mapping_LM(input_file: str, output_file: str, stage: Dict[str, Any], context: Dict[str, Any]) -> str:
    """LoD Mapping: assign a Level-of-Detail to each mapped element."""
    logger.info("Stage LM, input: %s, output: %s", input_file, output_file)

    rules = B2GM_LM.rules_from_stage(stage)
    mapped = context.get("em_mapped")
    if mapped is None:
        # EM did not run before LM; fall back to (re)parsing the source
        try:
            objects = B2GM_BIM.BIM().parse(input_file)
            mapped = objects
        except Exception:
            logger.warning("LM has no elements to process; copying input forward")
            if os.path.abspath(input_file) != os.path.abspath(output_file):
                shutil.copy(input_file, output_file)
            return output_file

    tagged = B2GM_LM.assign_lod(mapped, rules)
    context["lm_mapped"] = tagged
    lods = sorted({o.get("_lod") for o in tagged})
    logger.info("LM assigned LoD to %d elements: %s", len(tagged), lods)

    # objects already carry _destination from EM, so an empty-rule stage still writes them
    B2GM_GIS.GIS().store(output_file, tagged, stage)
    return output_file


_STAGE_FUNCS = {
    "PD": mapping_PD,
    "CM": mapping_CM,
    "EM": mapping_EM,
    "LM": mapping_LM,
}


def mapping_ifc_to_target(input_file: str, output_file: str, pipeline_file: str,
                          output_dir: str = "output") -> Dict[str, Any]:
    """Run the full pipeline described by ``pipeline_file`` on ``input_file``.

    Every intermediate and final artefact is written under ``output_dir`` so the
    source tree stays clean.  A stage ``output`` is treated as a bare filename
    (its directory part is ignored) and re-rooted at ``output_dir``.
    """
    with open(pipeline_file, "r", encoding="utf-8") as f:
        pipelines = json.load(f)

    pipeline: List[Dict[str, Any]] = pipelines["BIM_GIS_mapping.pipeline"]

    os.makedirs(output_dir, exist_ok=True)

    context: Dict[str, Any] = {}
    current_input = input_file
    final_output = os.path.join(output_dir, os.path.basename(output_file))

    for stage in pipeline:
        stage_type = stage.get("type")
        if "output" in stage:
            current_output = os.path.join(output_dir, os.path.basename(stage["output"]))
        else:
            fname, fext = os.path.splitext(os.path.basename(current_input))
            current_output = os.path.join(output_dir, f"{fname}_{stage_type}{fext}")

        func = _STAGE_FUNCS.get(stage_type)
        if func is None:
            logger.warning("Unknown stage type: %s (skipped)", stage_type)
            continue

        current_output = func(current_input, current_output, stage, context)
        if stage_type in ("EM", "LM"):
            final_output = current_output
        current_input = current_output

    context["final_output"] = final_output
    logger.info("Pipeline finished, final output: %s", final_output)
    return context


def save_models(context: Dict[str, Any], output_dir: str) -> Dict[str, str]:
    """Save the BIM and GIS conceptual models as JSON (per the ISO 19166 XSDs).

    Uses the objects already held in ``context`` (no re-parsing): the parsed BIM
    objects for ``bim_model.json`` and the LM/EM-mapped objects for
    ``gis_model.json``.  Returns the written paths.
    """
    written: Dict[str, str] = {}
    objects = context.get("objects") or []
    if objects:
        path = os.path.join(output_dir, "bim_model.json")
        written["bim"] = B2GM_BIM.BIM().save(path, objects)

    gis_objects = context.get("lm_mapped") or context.get("em_mapped") or []
    if gis_objects:
        path = os.path.join(output_dir, "gis_model.json")
        written["gis"] = B2GM_GIS.GIS().save(path, gis_objects)
    return written


DEFAULT_INPUT = os.path.join("input_data", "duplex_apartment.ifc")
DEFAULT_PIPELINE = os.path.join("input_data", "B2GM_example.json")
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_OUTPUT = "city.gml"


def main():
    parser = argparse.ArgumentParser(
        prog="B2GM_main.py",
        description=(
            "ISO 19166 B2GM BIM-to-GIS conceptual mapping pipeline.\n\n"
            "Runs an IFC (BIM) file through four mapping stages driven by a pipeline\n"
            "JSON config:\n"
            "  PD  Perspective Definition  - select the required BIM subset\n"
            "  CM  Coordinate Mapping      - source CRS -> destination CRS\n"
            "  EM  Element Mapping         - IFC element -> GIS/CityGML element\n"
            "  LM  LoD Mapping             - assign a GIS Level-of-Detail\n\n"
            "By convention input data and the pipeline config live under 'input_data/'\n"
            "and every result (intermediate + final) is written under 'output/'.\n"
            "These are the defaults, so a bare 'python B2GM_main.py' runs the shipped\n"
            "example end to end."
        ),
        epilog=(
            "Examples:\n"
            "  # Run the shipped example (input_data/ -> output/)\n"
            "  python B2GM_main.py\n\n"
            "  # Explicit paths\n"
            "  python B2GM_main.py --input input_data/duplex_apartment.ifc \\\n"
            "                      --pipeline input_data/B2GM_example.json \\\n"
            "                      --output-dir output\n\n"
            "  # Change the final CityGML filename (still written under --output-dir)\n"
            "  python B2GM_main.py --output my_city.gml\n\n"
            "Outputs written to <output-dir>/ (names come from the pipeline JSON):\n"
            "  intermediate.ifc     + .pd.json   PD perspective (selected elements)\n"
            "  intermediate_CM.ifc  + .cm.json   CM georeferencing summary\n"
            "  city.gml                          EM result (CityGML)\n"
            "  city_LoD.gml                      LM result (CityGML with per-element LoD)\n"
            "  bim_model.json / gis_model.json   conceptual models per ISO 19166 XSD (with --save-json)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help=f"Input IFC file (default: {DEFAULT_INPUT})")
    parser.add_argument("--pipeline", default=DEFAULT_PIPELINE,
                        help=f"Mapping pipeline JSON config (default: {DEFAULT_PIPELINE})")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, dest="output_dir",
                        help=f"Directory for all intermediate and final results (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"Final CityGML filename, written under --output-dir (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--save-json", action="store_true", dest="save_json",
                        help="Also save the BIM/GIS conceptual models as JSON (per ISO 19166 XSD) under --output-dir")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        logger.error("Input file does not exist: %s", args.input)
        return

    ext = os.path.splitext(args.input)[1].lower()
    if ext != ".ifc":
        logger.error("Input must be an .ifc file, got: %s", args.input)
        return

    if not os.path.exists(args.pipeline):
        logger.error("Pipeline config does not exist: %s", args.pipeline)
        return

    context = mapping_ifc_to_target(args.input, args.output, args.pipeline, args.output_dir)
    if args.save_json:
        written = save_models(context, args.output_dir)
        logger.info("Saved conceptual models: %s", ", ".join(written.values()))
    logging.info("Finished")


if __name__ == "__main__":
    main()
