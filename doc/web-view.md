# Web view

```powershell
python B2GM_main.py --web          # or: python B2GM_web.py / b2gm-web
run_web.bat                        # Windows launcher
./run_web.sh                       # Linux / macOS launcher
```

Opens a three panel workspace at `http://127.0.0.1:8000` on the stdlib HTTP
server — no web framework, no CDN, nothing to install beyond the core
dependencies.

| Panel | Contents |
|-------|----------|
| Left | input folder tree, and the PD/CM/EM/LM stage properties as editable fields: scalars as one-line inputs, each rule as a property grid listing the keys the standard defines for that stage, filled or not, with fixed choices (`lod`, `PSet_operation`) as drop-downs and nested values as json; a `json` toggle shows the raw form |
| Middle | WebGL canvas — drag to orbit, wheel to zoom, right drag to pan; shaded, shaded + edges, wireframe, x-ray, flat + edges or hidden line rendering, an opacity slider and view reset; an axis gizmo whose X/Y/Z tips snap the camera (click again for the far side); a legend lists the feature classes with counts and toggles each on or off |
| Right | output folder tree, and a tabbed pane with the file preview and the stage log |

The header carries the pipeline flags that make sense in a browser: the CityGML
version (2.0, 3.0, or whatever the pipeline file says) and whether to also save
the BIM/GIS conceptual models as JSON. Clicking a `.json` in the input tree that
holds a pipeline loads it into the stage panel, which is the `--pipeline` flag;
the panel head names the file in use. The PD/CM/EM/LM chips in the header open
that stage in the panel and put its output file on the canvas, and the lit chip
is the stage whose output is currently shown.

Both side panels are resized by dragging the splitters (the widths are
remembered). Below 900 px the three panels do not fit side by side and a drag
splitter is no use on touch, so the layout becomes one panel at a time behind a
tab bar; `?view=left|middle|right` opens a particular one, and `?theme=`,
`?lang=`, `?mode=shaded|edges|wireframe|xray|flat|hidden`, `?opacity=<15..100>`, `?select=<output file>`, `?version=` and `?hide=` preset the
rest, so a view can be shared as a link. **Run pipeline** executes PD → CM → EM → LM on the IFC selected in
the input tree and streams the stage log back, then reloads the output tree and
the canvas.

Clicking a file renders it: `.ifc` (the source model, coloured by IFC type),
`.gml` (CityGML), `.json` (`bim_model.json` / `gis_model.json`) and `.obj`.
Everything else, and a model file with nothing to draw, opens as text in the middle panel as well as in the preview pane.

A CityGML file placed in Web Mercator is drawn at true ground proportions:
EPSG:3857 stretches x and y by 1/cos(latitude) but leaves z alone, so a building
taken straight from it looks too wide for its height and does not line up with
the IFC it came from. The header names the CRS when a correction is applied.

**Drop an `.ifc` on the canvas** to convert it, optionally together with a
pipeline `.json`. The model runs through PD → CM → EM → LM and the result is
rendered straight away:

```
POST /api/convert     multipart: ifc=<model.ifc> [pipeline=<config.json>] [version=2.0|3.0] [save_json=1]
POST /api/run         json: {"path": "<in input tree>", "pipeline": "<.json in input tree>", "version": "3.0", "save_json": true}
GET  /api/pipeline?path=<.json in input tree>    describe a pipeline other than the default
```

Sending your own config is the point of it — change an `EM_rule` destination and
the feature classes in the result change with it, which is what the standard is
actually about. Without a config the bundled example rules are used.

The upload lands in the input tree under `uploads/` and the result under
`output/<model>/`, so both show up where you look for them; a repeated name gets
a `_2` suffix rather than overwriting. Editing a stage field in the left panel
and pressing **Apply & run** sends the edited config the same way, which is the
quickest way to see a rule change move features between classes.

The conversion runs in a separate process, so a large or malformed model times
out (180 s) rather than wedging the view. Uploads are capped at 50 MB.

Clicking a class in the legend hides it, which is how you look inside the model:
switch off the building block and the wall surfaces and what remains are the
LOD1 room solids the LM operators produced, plus the windows and doors. The
opacity slider and the x-ray mode do the same without hiding anything.

The theme (dark / light) and language (English / 한국어) toggles are in the
header and persist. Both can also be set from the URL, which makes a view
shareable: `?theme=light&lang=ko&hide=WallSurface,CityModel.Building`.

| Option | Default | Meaning |
|--------|---------|---------|
| `--port` | `8000` | listening port |
| `--host` | `127.0.0.1` | bind address |
| `--no-browser` | off | do not open a browser window |
| `--input-dir` / `--output-dir` / `--pipeline` | `input_data` / `output` / `input_data/B2GM_example.json` | workspace roots (`B2GM_web.py` only; `--web` reuses the pipeline options) |

File access is confined to the two workspace roots — a path that escapes them is
refused.

### Deploying the web view

`Dockerfile` and `fly.toml` deploy the view to [Fly.io](https://fly.io). The
image converts the bundled sample at build time, so the first visitor lands on a
model rather than an empty canvas:

```bash
fly launch --no-deploy --copy-config   # first time: pick the app name and region
fly deploy
fly open
```

The container reads `B2GM_HOST` and `PORT` from the environment, which is why the
local default stays on loopback: running the tool on a laptop is not exposed to
the network unless you ask for it.

`fly.toml` sets `auto_stop_machines` with `min_machines_running = 0`, so the
machine sleeps between visitors, and `max_machines_running = 1`, which caps what
the unauthenticated pipeline endpoint can cost. A `shared-cpu-1x` with 512 MB is
enough — the pipeline peaks around 196 MB.

> The view has no authentication, and both `/api/run` and `/api/convert` execute
> the pipeline, so treat a public deployment as a demo rather than a service. A
> pipeline config is executable input — `PD_logic_view.ETL_module` imports and
> calls what it names, and `external_data_source` reads the path it is given — so
> treat one the way you would treat code. Fly.io runs each machine as its own
> microVM, which is what makes accepting uploads on a throwaway demo reasonable;
> it has no free tier, so a deployed machine costs money even while idle-stopped.
