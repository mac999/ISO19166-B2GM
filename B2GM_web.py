"""
B2GM web view - browser front end for the mapping pipeline.

Serves a three panel workspace on the stdlib HTTP server (no extra
dependency): the input folder tree and the PD/CM/EM/LM stage properties on the
left, a WebGL canvas in the middle and the output folder tree on the right.

Usage:
    python B2GM_web.py
    python B2GM_web.py --port 8000 --no-browser
    python B2GM_main.py --web

Author:
    Taewook Kang (laputa99999@gmail.com)

Date:
    2026-09
"""

from __future__ import annotations

import argparse
import email
import email.policy
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))


def _static_dir() -> str:
    """Locate the web assets: next to this module in a clone or editable
    install, else under the prefix where the wheel puts its data files."""
    for candidate in (os.path.join(HERE, "web"),
                      os.path.join(sys.prefix, "share", "b2gm", "web"),
                      os.path.join(os.path.dirname(HERE), "share", "b2gm", "web")):
        if os.path.isfile(os.path.join(candidate, "index.html")):
            return candidate
    return os.path.join(HERE, "web")


STATIC_DIR = _static_dir()

MODEL_SUFFIXES = (".gml", ".json", ".obj")
TEXT_SUFFIXES = (".json", ".gml", ".xml", ".csv", ".txt", ".md", ".ifc", ".obj")
PREVIEW_BYTES = 64 * 1024
MAX_BODY_BYTES = 64 * 1024           # JSON requests
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # an uploaded IFC plus its pipeline config
CONVERT_TIMEOUT = 180                # one conversion must not wedge the view

# GIS class -> RGB, so the canvas colours features the way a CityGML viewer does
CLASS_COLORS = {
    "CityModel.Building": [0.85, 0.72, 0.42],
    "WallSurface": [0.80, 0.78, 0.72],
    "RoofSurface": [0.78, 0.32, 0.28],
    "GroundSurface": [0.45, 0.42, 0.38],
    "FloorSurface": [0.62, 0.60, 0.56],
    "CeilingSurface": [0.70, 0.74, 0.80],
    "Window": [0.35, 0.66, 0.86],
    "Door": [0.72, 0.50, 0.28],
    "Room": [0.42, 0.72, 0.55],
    "BuildingInstallation": [0.58, 0.52, 0.70],
    "BuildingStorey": [0.50, 0.55, 0.60],
    "LandUse": [0.40, 0.60, 0.35],
    "GenericCityObject": [0.60, 0.60, 0.60],
}
DEFAULT_COLOR = [0.65, 0.65, 0.65]


class Workspace:
    """Paths and pipeline the web view works against."""

    def __init__(self, input_dir: str, output_dir: str, pipeline: str, output: str):
        self.input_dir = os.path.abspath(input_dir)
        self.output_dir = os.path.abspath(output_dir)
        self.pipeline = os.path.abspath(pipeline)
        self.output = output

    def default_input(self) -> str:
        """First IFC in the input folder, so the view opens on something real."""
        if not os.path.isdir(self.input_dir):
            return ""
        return next((n for n in sorted(os.listdir(self.input_dir))
                     if n.lower().endswith(".ifc")), "")

    def roots(self) -> Dict[str, str]:
        return {"input": self.input_dir, "output": self.output_dir}

    def resolve(self, side: str, rel: str) -> str:
        """Resolve a client path inside a root; raises on traversal attempts."""
        root = self.roots().get(side)
        if root is None:
            raise ValueError(f"unknown side: {side}")
        path = os.path.abspath(os.path.join(root, rel or ""))
        if path != root and not path.startswith(root + os.sep):
            raise ValueError("path outside the workspace")
        return path


# ---------------------------------------------------------------------------
# folder tree
# ---------------------------------------------------------------------------
def build_tree(root: str, rel: str = "") -> Dict[str, Any]:
    path = os.path.join(root, rel)
    node: Dict[str, Any] = {
        "name": os.path.basename(path) or os.path.basename(root),
        "path": rel.replace(os.sep, "/"),
        "type": "dir",
        "children": [],
    }
    if not os.path.isdir(path):
        return node
    for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower())):
        child_rel = os.path.join(rel, entry.name)
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_dir():
            node["children"].append(build_tree(root, child_rel))
        else:
            suffix = os.path.splitext(entry.name)[1].lower()
            node["children"].append({
                "name": entry.name,
                "path": child_rel.replace(os.sep, "/"),
                "type": "file",
                "size": entry.stat().st_size,
                "ext": suffix,
                "viewable": suffix in MODEL_SUFFIXES,
            })
    return node


# ---------------------------------------------------------------------------
# pipeline description
# ---------------------------------------------------------------------------
STAGE_TITLES = {
    "PD": ("Perspective Definition", "관점 정의"),
    "CM": ("Coordinate Mapping", "좌표 매핑"),
    "EM": ("Element Mapping", "요소 매핑"),
    "LM": ("LoD Mapping", "LoD 매핑"),
}


def describe_pipeline(path: str) -> Dict[str, Any]:
    """Flatten a pipeline file into per-stage property rows for the left panel."""
    if not os.path.exists(path):
        return {"path": path, "stages": []}
    with open(path, encoding="utf-8") as f:
        document = json.load(f)
    stages = []
    for stage in document.get("BIM_GIS_mapping.pipeline", []):
        kind = stage.get("type", "?")
        title_en, title_ko = STAGE_TITLES.get(kind, (kind, kind))
        properties = []
        for key, value in stage.items():
            if key == "type":
                continue
            properties.append({
                "key": key,
                "value": value if isinstance(value, str) else json.dumps(
                    value, ensure_ascii=False, indent=1),
                "structured": not isinstance(value, str),
            })
        stages.append({
            "type": kind,
            "name": stage.get("name", ""),
            "title_en": title_en,
            "title_ko": title_ko,
            "output": stage.get("output", ""),
            "properties": properties,
        })
    return {"path": path, "stages": stages}


# ---------------------------------------------------------------------------
# model readers -> {features: [{name, gis_class, lod, verts, faces, color}]}
# ---------------------------------------------------------------------------
def _feature(name: str, gis_class: str, lod: str, verts: List[float],
             faces: List[int], attrs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "name": name,
        "gis_class": gis_class,
        "lod": lod,
        "verts": verts,
        "faces": faces,
        "color": CLASS_COLORS.get(gis_class, DEFAULT_COLOR),
        "attributes": attrs or {},
    }


def read_model_json(path: str) -> List[Dict[str, Any]]:
    """Read a B2GM GIS/BIM conceptual model JSON."""
    import B2GM_BIM
    import B2GM_GIS

    with open(path, encoding="utf-8") as f:
        head = json.load(f)
    if "GIS_model" in head:
        objects = B2GM_GIS.GIS().load(path)
        key = "_destination"
    elif "BIM_model" in head:
        objects = B2GM_BIM.BIM().load(path)
        key = "ifc_type"
    else:
        return []
    features = []
    for obj in objects:
        geom = obj.get("geometry") or {}
        if not geom.get("faces"):
            continue
        features.append(_feature(
            obj.get("name", ""), obj.get(key, ""), obj.get("_lod", ""),
            [float(c) for c in geom["verts"]], [int(i) for i in geom["faces"]],
            {"GUID": obj.get("GUID", ""), "ifc_type": obj.get("ifc_type", "")},
        ))
    return features


# CityGML features that carry geometry; openings and rooms nest inside the
# boundary surfaces and buildings above them, so each needs its own frame.
FEATURE_TAGS = {
    "Building", "BuildingPart",
    "WallSurface", "RoofSurface", "GroundSurface", "FloorSurface",
    "CeilingSurface", "ClosureSurface", "OuterFloorSurface", "OuterCeilingSurface",
    "Window", "Door",
    "Room", "BuildingRoom",
    "BuildingInstallation", "IntBuildingInstallation",
    "LandUse", "GenericCityObject",
    # CityGML 3.0 additions
    "Storey", "BuildingUnit", "BuildingConstructiveElement", "GenericLogicalSpace",
}

GML_NAME = "{http://www.opengis.net/gml}name"
GML32_NAME = "{http://www.opengis.net/gml/3.2}name"

_LOCAL = re.compile(r"\{.*\}")


def _tag(element) -> str:
    return _LOCAL.sub("", element.tag)


def read_citygml(path: str) -> List[Dict[str, Any]]:
    """Read the triangles of every CityGML feature that carries geometry."""
    features: List[Dict[str, Any]] = []
    stack: List[Dict[str, Any]] = []
    for event, element in ET.iterparse(path, events=("start", "end")):
        name = _tag(element)
        if event == "start":
            if name in FEATURE_TAGS:
                stack.append({"class": name, "name": "", "verts": [], "faces": [],
                              "attrs": {}, "index": {}})
            continue
        if not stack:
            if name in ("cityObjectMember",):
                element.clear()
            continue
        current = stack[-1]
        if element.tag in (GML_NAME, GML32_NAME) and not current["name"]:
            current["name"] = (element.text or "").strip()
        elif name in ("stringAttribute", "StringAttribute"):
            # 2.0 puts the key in a name attribute, 3.0 in a child element
            key = element.get("name") or next(
                (c.text for c in element if _tag(c) == "name"), "")
            value = next((c.text for c in element if _tag(c) == "value"), "")
            # geometry-less elements are written as attributes of the building, so
            # only the first value (the feature's own) identifies the feature
            if key:
                current["attrs"].setdefault(key.strip(), (value or "").strip())
        elif name == "posList":
            _add_ring(current, (element.text or "").split())
        elif name == current["class"]:
            done = stack.pop()
            if done["faces"]:
                features.append(_feature(
                    done["name"] or done["class"],
                    done["attrs"].get("gis_class", done["class"]),
                    done["attrs"].get("lod", ""),
                    done["verts"], done["faces"], done["attrs"]))
            element.clear()
    return features


def _add_ring(feature: Dict[str, Any], numbers: List[str]):
    """Triangulate one gml:LinearRing (a closed polygon) into the feature mesh."""
    coords = [float(n) for n in numbers]
    points = [tuple(coords[i:i + 3]) for i in range(0, len(coords) - 2, 3)]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 3:
        return
    index = feature["index"]
    ids = []
    for point in points:
        key = point
        if key not in index:
            index[key] = len(feature["verts"]) // 3
            feature["verts"].extend(point)
        ids.append(index[key])
    for i in range(1, len(ids) - 1):
        feature["faces"].extend([ids[0], ids[i], ids[i + 1]])


def read_obj(path: str) -> List[Dict[str, Any]]:
    verts: List[float] = []
    faces: List[int] = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "v" and len(parts) >= 4:
                verts.extend(float(c) for c in parts[1:4])
            elif parts[0] == "f" and len(parts) >= 4:
                ids = [int(p.split("/")[0]) - 1 for p in parts[1:]]
                for i in range(1, len(ids) - 1):
                    faces.extend([ids[0], ids[i], ids[i + 1]])
    return [_feature(os.path.basename(path), "GenericCityObject", "", verts, faces)] if faces else []


def read_model(path: str) -> Dict[str, Any]:
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".json":
        features = read_model_json(path)
    elif suffix == ".gml":
        features = read_citygml(path)
    elif suffix == ".obj":
        features = read_obj(path)
    else:
        raise ValueError(f"cannot display {suffix} in the 3D view")
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for feature in features:
        verts = feature["verts"]
        for axis in range(3):
            column = verts[axis::3]
            if column:
                lo[axis] = min(lo[axis], min(column))
                hi[axis] = max(hi[axis], max(column))
    if lo[0] == float("inf"):
        lo, hi = [0.0] * 3, [1.0] * 3
    return {"features": features, "bounds": {"min": lo, "max": hi},
            "triangles": sum(len(f["faces"]) // 3 for f in features)}


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
def run_b2gm(input_file: str, pipeline: str, output_dir: str,
             version: Optional[str] = None,
             timeout: int = CONVERT_TIMEOUT) -> Dict[str, Any]:
    """Run the mapping pipeline and capture its log for the browser.

    B2GM_main runs as a separate process: a large or malformed model then times
    out instead of wedging the view, which a call in this process could not do.
    """
    command = [sys.executable, os.path.join(HERE, "B2GM_main.py"),
               "--input", input_file, "--pipeline", pipeline,
               "--output-dir", output_dir]
    if version:
        command += ["--citygml-version", version]
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, cwd=HERE)
    except subprocess.TimeoutExpired:
        return {"ok": False, "log": [f"the pipeline timed out after {timeout}s"]}
    # the stage log goes to stderr; tqdm redraws are noise in a browser
    log = [line for line in (proc.stderr or "").splitlines() if "it/s]" not in line]
    if proc.returncode != 0:
        return {"ok": False, "log": log or [(proc.stdout or "").strip()]}
    return {"ok": True, "log": log}


def _safe_name(name: str, default: str) -> str:
    """Keep only the basename, and only characters that cannot escape a path."""
    base = os.path.basename(str(name or "").replace("\\", "/"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return cleaned or default


def parse_multipart(content_type: str, body: bytes) -> Dict[str, Tuple[str, bytes]]:
    """Return ``{field: (filename, content)}`` from a multipart body."""
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    message = email.message_from_bytes(raw, policy=email.policy.default)
    parts: Dict[str, Tuple[str, bytes]] = {}
    if not message.is_multipart():
        return parts
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        parts[name] = (part.get_filename() or "", part.get_payload(decode=True) or b"")
    return parts


def convert_upload(ifc: Tuple[str, bytes], pipeline: Optional[Tuple[str, bytes]],
                   version: Optional[str], fallback_pipeline: str) -> Dict[str, Any]:
    """Run the pipeline over an uploaded IFC and return the rendered result.

    The work happens in a throwaway directory and in a separate process, so a
    huge or malformed model times out instead of wedging the view, and nothing
    is left behind afterwards.
    """
    work = tempfile.mkdtemp(prefix="b2gm-upload-")
    try:
        input_dir = os.path.join(work, "input")
        output_dir = os.path.join(work, "output")
        os.makedirs(input_dir)
        ifc_path = os.path.join(input_dir, _safe_name(ifc[0], "model.ifc"))
        with open(ifc_path, "wb") as f:
            f.write(ifc[1])

        if pipeline and pipeline[1].strip():
            pipeline_path = os.path.join(input_dir, _safe_name(pipeline[0], "pipeline.json"))
            with open(pipeline_path, "wb") as f:
                f.write(pipeline[1])
            try:
                json.loads(pipeline[1].decode("utf-8"))
            except Exception as exc:
                return {"ok": False, "log": [f"pipeline config is not valid JSON: {exc}"]}
        else:
            pipeline_path = fallback_pipeline

        result = run_b2gm(ifc_path, pipeline_path, output_dir, version)
        if not result["ok"]:
            return result

        produced = sorted(
            (n for n in os.listdir(output_dir) if n.lower().endswith(".gml")),
            key=lambda n: os.path.getmtime(os.path.join(output_dir, n)))
        if not produced:
            return {"ok": False,
                    "log": result["log"] + ["the pipeline produced no CityGML"]}
        final = produced[-1]
        return {"ok": True, "log": result["log"], "name": final,
                "model": read_model(os.path.join(output_dir, final))}
    finally:
        shutil.rmtree(work, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    workspace: Workspace
    server_version = "B2GM"
    protocol_version = "HTTP/1.1"
    # http.server keeps a thread per connection and has no timeout of its own,
    # so a stalled client would hold one open indefinitely
    timeout = 30

    def log_message(self, fmt, *args):  # keep the console readable
        logger.debug(fmt, *args)

    # -- helpers ------------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200):
        self._send(status, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400):
        self._json({"error": message}, status)

    def _static(self, name: str):
        path = os.path.abspath(os.path.join(STATIC_DIR, name))
        if not path.startswith(STATIC_DIR) or not os.path.isfile(path):
            return self._error("not found", 404)
        kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            self._send(200, f.read(), f"{kind}; charset=utf-8")

    # -- routes -------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        route = url.path
        try:
            if route in ("/", "/index.html"):
                return self._static("index.html")
            if route.startswith("/static/"):
                return self._static(route[len("/static/"):])
            if route == "/api/config":
                return self._json({
                    "input_dir": self.workspace.input_dir,
                    "output_dir": self.workspace.output_dir,
                    "pipeline": self.workspace.pipeline,
                    "output": self.workspace.output,
                    "input_default": self.workspace.default_input(),
                })
            if route == "/api/tree":
                side = query.get("side", "input")
                root = self.workspace.roots().get(side)
                if root is None:
                    return self._error("unknown side")
                return self._json(build_tree(root))
            if route == "/api/pipeline":
                return self._json(describe_pipeline(self.workspace.pipeline))
            if route == "/api/model":
                path = self.workspace.resolve(query.get("side", "output"), query.get("path", ""))
                if not os.path.isfile(path):
                    return self._error("not found", 404)
                return self._json(read_model(path))
            if route == "/api/file":
                path = self.workspace.resolve(query.get("side", "output"), query.get("path", ""))
                if not os.path.isfile(path):
                    return self._error("not found", 404)
                suffix = os.path.splitext(path)[1].lower()
                if suffix not in TEXT_SUFFIXES:
                    return self._json({"text": "", "binary": True,
                                       "size": os.path.getsize(path)})
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read(PREVIEW_BYTES)
                return self._json({"text": text, "binary": False,
                                   "size": os.path.getsize(path),
                                   "truncated": os.path.getsize(path) > PREVIEW_BYTES})
        except ValueError as exc:
            return self._error(str(exc))
        except Exception as exc:
            logger.exception("GET %s failed", route)
            return self._error(str(exc), 500)
        self._error("not found", 404)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/convert":
            return self._convert()
        if url.path != "/api/run":
            return self._error("not found", 404)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            return self._error("request body too large", 413)
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            path = self.workspace.resolve("input", payload.get("path", ""))
        except ValueError as exc:
            return self._error(str(exc))
        if not os.path.isfile(path) or not path.lower().endswith(".ifc"):
            return self._error("select an .ifc file in the input tree")
        self._json(run_b2gm(path, self.workspace.pipeline, self.workspace.output_dir))


    def _convert(self):
        """Run the pipeline over an uploaded IFC (and optional pipeline config)."""
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            return self._error(
                f"upload too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)", 413)
        content_type = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in content_type:
            return self._error("expected a multipart upload")
        try:
            parts = parse_multipart(content_type, self.rfile.read(length))
        except Exception as exc:
            return self._error(f"could not read the upload: {exc}")

        ifc = parts.get("ifc")
        if not ifc or not ifc[1]:
            return self._error("attach an .ifc file as the 'ifc' field")
        if not ifc[0].lower().endswith(".ifc"):
            return self._error("the model must be an .ifc file")

        version = None
        if "version" in parts:
            try:
                import B2GM_GIS

                version = B2GM_GIS.normalise_version(parts["version"][1].decode() or None)
            except Exception as exc:
                return self._error(str(exc))

        logger.info("converting upload %s (%.1f MB)", ifc[0], len(ifc[1]) / 1048576)
        result = convert_upload(ifc, parts.get("pipeline"), version,
                                self.workspace.pipeline)
        self._json(result)


def serve(workspace: Workspace, host: str = "127.0.0.1", port: int = 8000,
          open_browser: bool = True) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"workspace": workspace})
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_port}"
    logger.info("web view on %s (Ctrl+C to stop)", url)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    return server


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description="B2GM web view: input tree + pipeline stages, 3D canvas, output tree.")
    parser.add_argument("--input-dir", default="input_data", dest="input_dir")
    parser.add_argument("--output-dir", default="output", dest="output_dir")
    parser.add_argument("--pipeline", default=os.path.join("input_data", "B2GM_example.json"))
    parser.add_argument("--output", default="city.gml", help="final CityGML filename")
    # a container sets these through the environment; the local default stays
    # loopback so running the tool on a laptop is not exposed to the network
    parser.add_argument("--host", default=os.environ.get("B2GM_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--no-browser", action="store_true", dest="no_browser")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    workspace = Workspace(args.input_dir, args.output_dir, args.pipeline, args.output)
    server = serve(workspace, args.host, args.port, not args.no_browser)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
