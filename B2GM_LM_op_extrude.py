"""
LoD extrude operator for B2GM - generates GIS LOD1 block models from building
footprints, following the ISO 19166 B2G LM ``extrude`` operator (Clause 9,
Table 8).

The geometry generation is *general purpose* and dataset agnostic:

* extrusion is delegated to :mod:`B2GM_LM_operators` (numpy + shapely only), so
  no coordinate offsets, building names, CRS or field names are hard-coded;
* footprint attribute names, storey height, base offset, coordinate transform
  and colouring are all supplied through the LoD mapping configuration file;
* heavy dependencies are optional - ``geopandas`` is only needed to *read*
  GeoJSON, and ``pyvista`` only to *visualise*; extrusion and OBJ/CSV export
  work without them.

Conventions:
        By default the LoD-mapping config lives under ``input_data/`` and every
        result (OBJ meshes + a properties CSV) is written under ``output/`` - the
        same layout the main pipeline (``B2GM_main.py``) uses.  A bare
        ``python B2GM_LM_op_extrude.py`` runs the shipped example end to end.

Usage:
        python B2GM_LM_op_extrude.py
        python B2GM_LM_op_extrude.py --config input_data/LoD1_mapping_example.json
        python B2GM_LM_op_extrude.py --show     # + open the 3D viewer (pyvista)

Reference:
        ISO/TS 19166 - Geographic information - BIM to GIS conceptual mapping.

Author:
        Taewook Kang (laputa99999@gmail.com)

Date:
        2024-01-02, 2024-06-22 (generalised 2026-07)
"""

import numpy as np, random, json, re, os, sys, time, logging, csv, argparse
from shapely.geometry import Polygon, MultiPolygon
from pyproj import CRS, Transformer
from tqdm import tqdm

import B2GM_LM_operators as OP

# Optional heavy dependencies (geospatial IO / 3D visualisation). The module
# imports without them; functions that need them raise a clear error only when
# actually called.
try:
    import geopandas as gpd
except Exception:  # pragma: no cover - optional
    gpd = None
try:
    import pyvista as pv
except Exception:  # pragma: no cover - optional
    pv = None
try:
    import pydeck as pdk
except Exception:  # pragma: no cover - optional
    pdk = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# approximate degrees-per-metre, used only to display un-projected WGS84 data
DEG_PER_METER = 1.0 / 111_111.0


def _require(module, name):
    if module is None:
        raise RuntimeError(
            f"Optional dependency '{name}' is required for this operation. "
            f"Install it with: pip install {name}"
        )
    return module


if pv is not None:  # pragma: no cover - informational
    logger.info("pyvista version: %s", pv.__version__)


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------
def latlon_to_utm(latitude, longitude, target_datum="WGS84"):
    """Transform a geographic (lat, lon) point to its UTM zone (easting, northing)."""
    utm_zone = int((longitude + 180) / 6) + 1
    is_northern = latitude >= 0

    utm_crs = CRS.from_dict(
        {"proj": "utm", "zone": utm_zone, "datum": target_datum, "south": not is_northern}
    )
    transformer = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    easting, northing = transformer.transform(longitude, latitude)

    return easting, northing, utm_zone


# ---------------------------------------------------------------------------
# Extrusion (B2G LM extrude operator)
# ---------------------------------------------------------------------------
def extrude_polygon(poly, height, base_offset=(0.0, 0.0, 0.0), transform_utm=False, height_scale=1.0):
    """Extrude a 2D shapely ``Polygon`` into a 3D :class:`B2GM_LM_operators.Solid`.

    Parameters
    ----------
    poly : shapely.geometry.Polygon
        The footprint polygon (in the source CRS).
    height : float
        Extrusion height in metres.
    base_offset : (x, y, z)
        Local origin subtracted from every vertex (e.g. a scene origin). Not
        hard-coded to any dataset - pass it explicitly via the config.
    transform_utm : bool
        If True, treat coords as (lon, lat) and reproject to the matching UTM
        zone (metres) before extruding.
    height_scale : float
        Multiplier applied to ``height`` (use ``DEG_PER_METER`` to keep the
        block proportional when extruding un-projected WGS84 coordinates).
    """
    xs, ys = poly.exterior.coords.xy
    xs, ys = list(xs), list(ys)
    ox, oy, oz = (list(base_offset) + [0.0, 0.0, 0.0])[:3]

    pts = []
    for x, y in zip(xs, ys):
        if transform_utm:
            easting, northing, _ = latlon_to_utm(y, x)  # x=lon, y=lat
            x, y = easting, northing
        pts.append((x - ox, y - oy))

    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]  # drop the closing duplicate; operators re-close it
    if len(pts) < 3:
        raise ValueError("footprint polygon must have at least 3 distinct vertices")

    ring = Polygon(pts)
    return OP.extrude(ring, (0.0, 0.0, 1.0), float(height) * float(height_scale), base_z=oz)


# ---------------------------------------------------------------------------
# GeoJSON -> extruded building solids
# ---------------------------------------------------------------------------
def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_footprints(input_geojson):
    """Yield ``(shapely_geometry, properties_dict)`` for every GeoJSON feature.

    Uses ``geopandas`` when available; otherwise falls back to the stdlib
    ``json`` reader plus ``shapely.geometry.shape`` (both already required), so
    the extrusion runs without the optional ``geopandas`` dependency.
    """
    if gpd is not None:
        gdf = gpd.read_file(input_geojson)
        for _, row in gdf.iterrows():
            props = {k: v for k, v in row.items() if k != "geometry"}
            yield row["geometry"], props
        return

    from shapely.geometry import shape

    with open(input_geojson, encoding="utf-8") as f:
        data = json.load(f)
    features = data.get("features", []) if isinstance(data, dict) else []
    for feat in features:
        geom = feat.get("geometry")
        yield (shape(geom) if geom else None), (feat.get("properties") or {})


def extrude_geojson(geometry_mapping, input_geojson, base_offset=(0.0, 0.0, 0.0)):
    """Extrude every footprint in a GeoJSON file into LOD1 solids.

    ``geometry_mapping`` (a config block) may define, all optional:

    ==================  =========================================  ==========
    key                 meaning                                    default
    ==================  =========================================  ==========
    ground_storey       property name for above-ground storeys     (none)
    underground_storey  property name for below-ground storeys     (none)
    storey_height       metres per storey                          3.0
    default_height      height when storey fields are absent       storey_height
    transform_utm       reproject (lon,lat) -> UTM before extrude  False
    height_scale        multiplier on the computed height          1.0
    ==================  =========================================  ==========

    Reading GeoJSON works with or without ``geopandas`` (see
    :func:`_read_footprints`).
    """
    meta = geometry_mapping or {}
    storey_height = _num(meta.get("storey_height", 3.0), 3.0)
    gnd_field = meta.get("ground_storey")
    ugr_field = meta.get("underground_storey")
    default_height = _num(meta.get("default_height", storey_height), storey_height)
    transform_utm = bool(meta.get("transform_utm", False))
    height_scale = _num(meta.get("height_scale", 1.0), 1.0)

    rows = list(_read_footprints(input_geojson))

    features = []
    for geometry, properties in tqdm(rows, total=len(rows), desc="extruding"):
        if gnd_field or ugr_field:
            ground = _num(properties.get(gnd_field)) if gnd_field else 0.0
            under = _num(properties.get(ugr_field)) if ugr_field else 0.0
            building_height = (ground + under) * storey_height
            underground_height = under * storey_height
        else:
            building_height, underground_height = default_height, 0.0
        if building_height <= 0:
            building_height = default_height

        if isinstance(geometry, Polygon):
            polys = [geometry]
        elif isinstance(geometry, MultiPolygon):
            polys = list(geometry.geoms)
        else:
            polys = []

        solids = []
        for p in polys:
            solid = extrude_polygon(p, building_height, base_offset, transform_utm, height_scale)
            if underground_height:
                solid.vertices[:, 2] -= underground_height  # sink below ground
            solids.append(solid)

        features.append({"properties": properties, "geometry": solids})

    return features


# ---------------------------------------------------------------------------
# Output (OBJ meshes + CSV of properties) - no pyvista/meshio required
# ---------------------------------------------------------------------------
def save_mesh_excel(features, out_folder):
    os.makedirs(out_folder, exist_ok=True)

    index = 0
    for feature in features:
        for mesh in feature["geometry"]:
            index += 1
            out_fname = os.path.join(out_folder, f"building_{index}.obj")
            if hasattr(mesh, "save_obj"):          # B2GM_LM_operators.Solid
                mesh.save_obj(out_fname)
            elif pv is not None and hasattr(mesh, "save"):  # pyvista mesh
                mesh.save(out_fname)

    # collect the union of all property keys for a stable CSV header
    keys = []
    for feature in features:
        for k in feature["properties"]:
            if k not in keys:
                keys.append(k)

    with open(os.path.join(out_folder, "building_properties.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", *keys])
        for i, feature in enumerate(features):
            props = feature["properties"]
            writer.writerow([i, *[props.get(k, "") for k in keys]])


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------
def _resolve_color(properties, style_rules, rng=random):
    """Pick a colour for a building from config style rules, else random.

    A style rule is ``{"property": <name>, "match": <regex>, "color": [r,g,b]}``.
    The first rule whose property value matches its regex wins.
    """
    for rule in style_rules or []:
        field = rule.get("property")
        pattern = rule.get("match", ".*")
        color = rule.get("color")
        if field is None or color is None:
            continue
        if re.search(pattern, str(properties.get(field, ""))):
            return tuple(color)
    return (rng.uniform(0.3, 1.0), rng.uniform(0.3, 1.0), rng.uniform(0.2, 0.3))


def visualize_geojson(geojson_path):
    _require(pdk, "pydeck")
    layer = pdk.Layer(
        "PolygonLayer",
        data=geojson_path,
        get_polygon="geometry.coordinates",
        get_fill_color=[255, 0, 0, 255],
        extruded=True,
        get_elevation="properties.Z",
    )
    view_state = pdk.ViewState(latitude=0, longitude=0, zoom=2)
    deck = pdk.Deck(layers=[layer], initial_view_state=view_state)
    deck.show()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def load_LoD_mapping_file(mapping_file):
    with open(mapping_file, encoding="utf-8") as f:
        return json.load(f)


def mapping(mapping_file, show_flag=False):
    """Run footprint -> LOD1 extrusion for every geometry block in the config."""
    cfg = load_LoD_mapping_file(mapping_file)
    style_rules = cfg.get("style", [])

    start_time = time.time()
    objects = []
    for g in cfg["geometry"]:
        base_offset = g.get("base_offset", [0.0, 0.0, 0.0])
        features = extrude_geojson(g, g["input"], base_offset)
        output_folder = g.get("output", os.path.join("output", "lod1_buildings"))
        save_mesh_excel(features, output_folder)
        logger.info("wrote %d building(s) to %s", sum(len(feat["geometry"]) for feat in features), output_folder)
        objects.extend(features)

    logger.info("LoD mapping execution time: %.4f seconds", time.time() - start_time)

    if show_flag:
        _require(pv, "pyvista")
        p = pv.Plotter()
        p.camera = pv.Camera()
        p.camera.position = (0.0, 0.0, 200.0)
        p.camera.focal_point = (0.0, 0.0, 0.0)
        p.camera.up = (0.0, 1.0, 0.0)
        p.reset_camera()

        for obj in objects:
            color = _resolve_color(obj["properties"], style_rules)
            for mesh in obj["geometry"]:
                pv_mesh = mesh.to_pyvista() if hasattr(mesh, "to_pyvista") else mesh
                p.add_mesh(pv_mesh, smooth_shading=False, color=color)

        p.show_axes()
        p.background_color = "black"
        p.reset_camera()
        p.show(title="City 3D buildings viewer")

    return objects


def _bundled_config():
    """Prefer the current directory's example config, else the copy shipped next
    to this module (so an editable install works from any working directory)."""
    cwd_path = os.path.join("input_data", "LoD1_mapping_example.json")
    if os.path.exists(cwd_path):
        return cwd_path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "input_data", "LoD1_mapping_example.json")


DEFAULT_CONFIG = _bundled_config()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "ISO 19166 B2G LM 'extrude' operator (Clause 9, Table 8).\n\n"
            "Reads building footprints (GeoJSON) listed in a LoD-mapping config and\n"
            "generates GIS LOD1 block models by extruding each footprint to a height\n"
            "derived from its storey-count attributes. Each solid is exported as a\n"
            "Wavefront OBJ mesh plus a CSV of the source attributes.\n\n"
            "By convention the config lives under 'input_data/' and every result is\n"
            "written under 'output/'. These are the defaults, so a bare\n"
            "'python B2GM_LM_op_extrude.py' runs the shipped example end to end."
        ),
        epilog=(
            "Config (JSON) keys per 'geometry' block:\n"
            "  input               GeoJSON of building footprints\n"
            "  output              destination folder for the OBJ + CSV results\n"
            "  ground_storey       property name for above-ground storey count\n"
            "  underground_storey  property name for below-ground storey count\n"
            "  storey_height       metres per storey (default 3.0)\n"
            "  transform_utm       reproject (lon,lat) -> UTM before extruding\n"
            "  height_scale        multiplier on the computed height\n"
            "  base_offset         [x,y,z] local origin subtracted from vertices\n\n"
            "Examples:\n"
            "  # Run the shipped example (input_data/ -> output/)\n"
            "  python B2GM_LM_op_extrude.py\n\n"
            "  # Explicit config, then open the 3D viewer\n"
            "  python B2GM_LM_op_extrude.py --config input_data/LoD1_mapping_example.json --show"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("config", nargs="?", default=DEFAULT_CONFIG,
                        help=f"LoD-mapping config JSON (default: {DEFAULT_CONFIG})")
    parser.add_argument("--config", dest="config_opt", default=None,
                        help="Same as the positional config argument (keyword form)")
    parser.add_argument("--show", action="store_true",
                        help="Open the 3D viewer after extrusion (requires pyvista)")
    args = parser.parse_args()

    config_path = args.config_opt or args.config
    if not os.path.exists(config_path):
        logger.error("Config file does not exist: %s", config_path)
        return

    mapping(config_path, show_flag=args.show)


if __name__ == "__main__":
    main()
