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
from typing import Any, Dict, List, Optional

import B2GM_BIM
import B2GM_CM
import B2GM_element
import B2GM_GIS
import B2GM_LM
import B2GM_PD

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _carry_objects(context: Dict[str, Any], output_file: str):
    """PD/CM copy the IFC forward unchanged, so the parsed objects stay valid;
    mark them as belonging to the new path so EM does not re-parse (and lose the
    PD logic/style result)."""
    if context.get("objects") is not None:
        context["objects_from"] = output_file


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
    _carry_objects(context, output_file)
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

    placement = summary.pop("placement", None)
    objects = context.get("objects")
    if placement is not None and objects is None:
        # CM may run before any stage has parsed the model
        objects = B2GM_BIM.BIM().parse(input_file)
        context["objects"] = objects
    if placement is not None and objects:
        moved = B2GM_CM.apply_placement(objects, placement)
        context["srs_name"] = placement.dest_crs
        summary["placement"] = placement.to_dict()
        summary["elements_transformed"] = moved
        logger.info("CM %s -> %s, %d elements placed at %s",
                    summary.get("source_crs"), summary.get("dest_crs"),
                    moved, summary.get("dest_origin"))
    else:
        logger.info("CM %s -> %s, origin: %s (geometry left in local coordinates)",
                    summary.get("source_crs"), summary.get("dest_crs"),
                    summary.get("dest_origin"))
    context["crs"] = summary
    _write_sidecar(output_file, "cm", summary)
    _carry_objects(context, output_file)

    if os.path.abspath(input_file) != os.path.abspath(output_file):
        shutil.copy(input_file, output_file)
    return output_file


def mapping_EM(input_file: str, output_file: str, stage: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Element Mapping: IFC elements -> GIS/CityGML elements."""
    logger.info("Stage EM, input: %s, output: %s", input_file, output_file)

    objects = context.get("objects")
    if objects is None or context.get("objects_from") != input_file:
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

    # write the mapped copies so the rule's PSet_operation result reaches CityGML
    version = B2GM_GIS.version_from_stage(stage, context.get("citygml_version"))
    B2GM_GIS.GIS().store(output_file, mapped, stage,
                         srs_name=context.get("srs_name"), version=version)
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
    version = B2GM_GIS.version_from_stage(stage, context.get("citygml_version"))
    B2GM_GIS.GIS().store(output_file, tagged, stage,
                         srs_name=context.get("srs_name"), version=version)
    return output_file


_STAGE_FUNCS = {
    "PD": mapping_PD,
    "CM": mapping_CM,
    "EM": mapping_EM,
    "LM": mapping_LM,
}


def mapping_ifc_to_target(input_file: str, output_file: str, pipeline_file: str,
                          output_dir: str = "output",
                          citygml_version: Optional[str] = None) -> Dict[str, Any]:
    """Run the full pipeline described by ``pipeline_file`` on ``input_file``.

    Every intermediate and final artefact is written under ``output_dir`` so the
    source tree stays clean.  A stage ``output`` is treated as a bare filename
    (its directory part is ignored) and re-rooted at ``output_dir``.
    """
    with open(pipeline_file, "r", encoding="utf-8") as f:
        pipelines = json.load(f)

    pipeline: List[Dict[str, Any]] = pipelines["BIM_GIS_mapping.pipeline"]

    os.makedirs(output_dir, exist_ok=True)

    # CityGML version: CLI wins, then the pipeline file, then the default
    version = B2GM_GIS.normalise_version(
        citygml_version or pipelines.get("citygml_version") or B2GM_GIS.DEFAULT_VERSION)
    logger.info("CityGML output version: %s", version)

    context: Dict[str, Any] = {"citygml_version": version}
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


_HERE = os.path.dirname(os.path.abspath(__file__))


def _bundled(*parts: str) -> str:
    """Resolve a bundled example path: prefer the current directory (running
    from a repo clone), else fall back to the location of this module (works for
    an editable install run from any working directory)."""
    cwd_path = os.path.join(*parts)
    if os.path.exists(cwd_path):
        return cwd_path
    return os.path.join(_HERE, *parts)


DEFAULT_INPUT = _bundled("input_data", "duplex_apartment.ifc")
DEFAULT_PIPELINE = _bundled("input_data", "B2GM_example.json")
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_OUTPUT = "city.gml"


def main():
    parser = argparse.ArgumentParser(
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
            "  # Emit CityGML 3.0 instead of 2.0\n"
            "  python B2GM_main.py --citygml-version 3.0\n\n"
            "  # Browse input, stages, 3D result and outputs in a browser\n"
            "  python B2GM_main.py --web\n\n"
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
    parser.add_argument("--citygml-version", dest="citygml_version",
                        choices=["2.0", "3.0"], default=None,
                        help="CityGML output version (default: the pipeline file's "
                             "'citygml_version', else 2.0). 3.0 keeps building storeys, "
                             "which 2.0 has no feature for.")
    parser.add_argument("--web", action="store_true",
                        help="Open the web view (input tree + stage properties, 3D canvas, output tree)")
    parser.add_argument("--port", type=int, default=8000, help="Web view port (with --web)")
    parser.add_argument("--no-browser", action="store_true", dest="no_browser",
                        help="Do not open a browser window (with --web)")
    args = parser.parse_args()

    if args.web:
        import B2GM_web

        os.makedirs(args.output_dir, exist_ok=True)
        workspace = B2GM_web.Workspace(os.path.dirname(args.input) or ".",
                                       args.output_dir, args.pipeline, args.output)
        server = B2GM_web.serve(workspace, port=args.port, open_browser=not args.no_browser)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("stopped")
        finally:
            server.server_close()
        return

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

    context = mapping_ifc_to_target(args.input, args.output, args.pipeline,
                                    args.output_dir, args.citygml_version)
    if args.save_json:
        written = save_models(context, args.output_dir)
        logger.info("Saved conceptual models: %s", ", ".join(written.values()))
    logging.info("Finished")


if __name__ == "__main__":
    main()
