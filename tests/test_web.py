"""Web view: workspace paths, folder tree, pipeline panel, model readers, HTTP."""
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request

import pytest

import B2GM_web as WEB

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


@pytest.fixture
def workspace(tmp_path):
    inputs = tmp_path / "in"
    outputs = tmp_path / "out"
    inputs.mkdir()
    outputs.mkdir()
    (inputs / "model.ifc").write_text("ISO-10303-21;", encoding="utf-8")
    (inputs / "notes.txt").write_text("hello", encoding="utf-8")
    (outputs / "sub").mkdir()
    (outputs / "sub" / "city.gml").write_text(GML, encoding="utf-8")
    pipeline = tmp_path / "pipe.json"
    pipeline.write_text(json.dumps({"BIM_GIS_mapping.pipeline": [
        {"type": "PD", "name": "pd", "output": "a.ifc", "data_view": [{"class": ".*"}]},
        {"type": "LM", "name": "lm", "output": "city_LoD.gml",
         "rule": [{"source": ".*", "lod": "LOD1"}]},
    ]}), encoding="utf-8")
    return WEB.Workspace(str(inputs), str(outputs), str(pipeline), "city.gml")


GML = """<?xml version="1.0" encoding="UTF-8"?>
<core:CityModel xmlns:core="http://www.opengis.net/citygml/2.0"
    xmlns:bldg="http://www.opengis.net/citygml/building/2.0"
    xmlns:gen="http://www.opengis.net/citygml/generics/2.0"
    xmlns:gml="http://www.opengis.net/gml">
  <core:cityObjectMember>
    <bldg:Building gml:id="b1">
      <gml:name>House</gml:name>
      <gen:stringAttribute name="gis_class"><gen:value>CityModel.Building</gen:value></gen:stringAttribute>
      <gen:stringAttribute name="lod"><gen:value>LOD1</gen:value></gen:stringAttribute>
      <bldg:lod1MultiSurface><gml:MultiSurface><gml:surfaceMember><gml:Polygon>
        <gml:exterior><gml:LinearRing>
          <gml:posList srsDimension="3">0 0 0 4 0 0 4 3 0 0 3 0 0 0 0</gml:posList>
        </gml:LinearRing></gml:exterior>
      </gml:Polygon></gml:surfaceMember></gml:MultiSurface></bldg:lod1MultiSurface>
      <bldg:boundedBy><bldg:WallSurface gml:id="w1">
        <gml:name>Wall</gml:name>
        <gen:stringAttribute name="gis_class"><gen:value>WallSurface</gen:value></gen:stringAttribute>
        <bldg:lod3MultiSurface><gml:MultiSurface><gml:surfaceMember><gml:Polygon>
          <gml:exterior><gml:LinearRing>
            <gml:posList srsDimension="3">0 0 0 4 0 0 4 0 3 0 0 0</gml:posList>
          </gml:LinearRing></gml:exterior>
        </gml:Polygon></gml:surfaceMember></gml:MultiSurface></bldg:lod3MultiSurface>
        <bldg:opening><bldg:Window gml:id="win1">
          <gml:name>Window</gml:name>
          <gen:stringAttribute name="gis_class"><gen:value>Window</gen:value></gen:stringAttribute>
          <bldg:lod3MultiSurface><gml:MultiSurface><gml:surfaceMember><gml:Polygon>
            <gml:exterior><gml:LinearRing>
              <gml:posList srsDimension="3">1 0 1 2 0 1 2 0 2 1 0 1</gml:posList>
            </gml:LinearRing></gml:exterior>
          </gml:Polygon></gml:surfaceMember></gml:MultiSurface></bldg:lod3MultiSurface>
        </bldg:Window></bldg:opening>
      </bldg:WallSurface></bldg:boundedBy>
    </bldg:Building>
  </core:cityObjectMember>
</core:CityModel>
"""


# --- workspace --------------------------------------------------------------
def test_resolve_blocks_traversal(workspace):
    assert workspace.resolve("input", "model.ifc").endswith("model.ifc")
    with pytest.raises(ValueError):
        workspace.resolve("input", "../secret")
    with pytest.raises(ValueError):
        workspace.resolve("nowhere", "x")


def test_default_input_picks_the_ifc(workspace):
    assert workspace.default_input() == "model.ifc"


# --- tree / pipeline --------------------------------------------------------
def test_build_tree_marks_viewable(workspace):
    tree = WEB.build_tree(workspace.output_dir)
    folder = next(n for n in tree["children"] if n["type"] == "dir")
    gml = folder["children"][0]
    assert gml["name"] == "city.gml" and gml["viewable"]
    assert gml["path"] == "sub/city.gml"


def test_describe_pipeline_flattens_stages(workspace):
    described = WEB.describe_pipeline(workspace.pipeline)
    kinds = [s["type"] for s in described["stages"]]
    assert kinds == ["PD", "LM"]
    pd = described["stages"][0]
    assert pd["title_ko"] == "관점 정의"
    keys = {p["key"] for p in pd["properties"]}
    assert {"name", "output", "data_view"} <= keys and "type" not in keys


def test_describe_pipeline_missing_file():
    assert WEB.describe_pipeline("nope.json")["stages"] == []


# --- model readers ----------------------------------------------------------
def test_read_citygml(workspace):
    model = WEB.read_model(os.path.join(workspace.output_dir, "sub", "city.gml"))
    classes = {f["gis_class"]: f for f in model["features"]}
    assert set(classes) == {"CityModel.Building", "WallSurface", "Window"}
    assert classes["CityModel.Building"]["lod"] == "LOD1"
    assert model["triangles"] == 4  # quad + wall triangle + window triangle
    assert model["bounds"]["max"] == [4.0, 3.0, 3.0]


def test_read_citygml_keeps_nested_openings_separate(workspace):
    """A window nested in bldg:opening must not be absorbed by its host wall."""
    model = WEB.read_model(os.path.join(workspace.output_dir, "sub", "city.gml"))
    window = next(f for f in model["features"] if f["gis_class"] == "Window")
    wall = next(f for f in model["features"] if f["gis_class"] == "WallSurface")
    assert window["name"] == "Window" and wall["name"] == "Wall"
    assert len(window["faces"]) // 3 == 1 and len(wall["faces"]) // 3 == 1


def test_read_obj(tmp_path):
    path = tmp_path / "block.obj"
    path.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n", encoding="utf-8")
    model = WEB.read_model(str(path))
    assert model["triangles"] == 2


def test_read_model_rejects_other_types(tmp_path):
    path = tmp_path / "a.ifc"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        WEB.read_model(str(path))


def test_read_model_json_roundtrip(tmp_path):
    import B2GM_GIS

    objects = [{"name": "W", "GUID": "g", "_destination": "WallSurface", "_lod": "LOD2",
                "pset": {}, "geometry": {"verts": [0, 0, 0, 1, 0, 0, 1, 1, 0],
                                         "faces": [0, 1, 2]}}]
    path = str(tmp_path / "gis_model.json")
    B2GM_GIS.GIS().save(path, objects)
    model = WEB.read_model(path)
    assert model["features"][0]["gis_class"] == "WallSurface"
    assert model["triangles"] == 1


# --- HTTP -------------------------------------------------------------------
@pytest.fixture
def server(workspace):
    httpd = WEB.serve(workspace, port=0, open_browser=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def get(base, path):
    with urllib.request.urlopen(base + path) as response:
        return response.status, response.read()


def get_error(base, path):
    try:
        urllib.request.urlopen(base + path)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())
    raise AssertionError("expected an error response")


def test_routes(server):
    status, body = get(server, "/")
    assert status == 200 and b"<canvas id=\"scene\">" in body
    assert get(server, "/static/app.js")[0] == 200

    config = json.loads(get(server, "/api/config")[1])
    assert config["input_default"] == "model.ifc"

    tree = json.loads(get(server, "/api/tree?side=input")[1])
    assert {c["name"] for c in tree["children"]} == {"model.ifc", "notes.txt"}

    model = json.loads(get(server, "/api/model?side=output&path=sub/city.gml")[1])
    assert model["triangles"] == 4

    preview = json.loads(get(server, "/api/file?side=input&path=model.ifc")[1])
    assert preview["text"].startswith("ISO-10303-21")


def test_traversal_is_refused(server):
    status, body = get_error(server, "/api/file?side=output&path=../../etc/passwd")
    assert status == 400 and "outside" in body["error"]


def test_missing_file_is_404(server):
    assert get_error(server, "/api/model?side=output&path=nope.gml")[0] == 404


# --- shipped assets ---------------------------------------------------------
def test_web_assets_exist():
    for name in ("index.html", "style.css", "app.js"):
        assert os.path.isfile(os.path.join(ROOT, "web", name))


# --- uploading a model (and optionally a config) to convert ------------------
def multipart(fields):
    """Build a multipart body: {name: (filename, bytes)}."""
    boundary = "----b2gmtest"
    out = b""
    for name, (filename, content) in fields.items():
        out += f"--{boundary}\r\n".encode()
        disposition = f'form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        out += f"Content-Disposition: {disposition}\r\n\r\n".encode()
        out += content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", out


def post(base, path, content_type, body):
    request = urllib.request.Request(base + path, data=body, method="POST")
    request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_parse_multipart_reads_both_parts():
    content_type, body = multipart({
        "ifc": ("a.ifc", b"ISO-10303-21;"),
        "pipeline": ("p.json", b"{}"),
    })
    parts = WEB.parse_multipart(content_type, body)
    assert parts["ifc"] == ("a.ifc", b"ISO-10303-21;")
    assert parts["pipeline"][1] == b"{}"


def test_safe_name_cannot_escape_a_directory():
    assert WEB._safe_name("../../etc/passwd", "x.ifc") == "passwd"
    assert WEB._safe_name("a/b/model.ifc", "x.ifc") == "model.ifc"
    assert WEB._safe_name("", "x.ifc") == "x.ifc"
    assert WEB._safe_name("...", "x.ifc") == "x.ifc"


def test_convert_needs_an_ifc(server):
    content_type, body = multipart({"pipeline": ("p.json", b"{}")})
    status, payload = post(server, "/api/convert", content_type, body)
    assert status == 400 and "ifc" in payload["error"]


def test_convert_rejects_other_extensions(server):
    content_type, body = multipart({"ifc": ("model.txt", b"nope")})
    status, payload = post(server, "/api/convert", content_type, body)
    assert status == 400 and ".ifc" in payload["error"]


def test_convert_rejects_a_plain_json_post(server):
    status, payload = post(server, "/api/convert", "application/json", b"{}")
    assert status == 400 and "multipart" in payload["error"]


def test_convert_reports_a_broken_pipeline_config(server):
    content_type, body = multipart({
        "ifc": ("m.ifc", b"ISO-10303-21;"),
        "pipeline": ("p.json", b"{ not json"),
    })
    status, payload = post(server, "/api/convert", content_type, body)
    assert payload["ok"] is False
    assert "not valid JSON" in payload["log"][0]


def test_convert_leaves_no_temporary_directory(server, tmp_path):
    import glob

    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "b2gm-upload-*")))
    content_type, body = multipart({"ifc": ("m.ifc", b"not really an ifc")})
    post(server, "/api/convert", content_type, body)
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "b2gm-upload-*")))
    assert after == before
