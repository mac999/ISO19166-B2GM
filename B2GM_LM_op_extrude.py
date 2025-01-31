'''
LoD Extrude Mapping Operator for B2GM to creates B2GM LoD mapping operator on ISO 19166 B2GM

Usage:
	python B2GM_LM_op_extrude.py <input> <output> <option>
	<input> - Input file path
	<output> - Output file path
	<option> - Option file path

Reference: 
	https://docs.pyvista.org/version/stable/api/core/_autosummary/pyvista.polydata.save#pyvista.PolyData.save
	https://docs.pyvista.org/version/stable/api/plotting/_autosummary/pyvista.Plotter.show.html

Author:
	Taewook Kang (laputa99999@gmail.com)

Date:
	2024-01-02
	2024-06-22
'''
import geopandas as gpd, numpy as np, pyvista as pv, pydeck as pdk, meshio, random, json, re, os, time, logging
from shapely.geometry import Polygon, MultiPolygon
from pyproj import Proj, transform
from tqdm import tqdm

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info('pyvista version: %s', pv.__version__)

# functions
def latlon_to_utm(latitude, longitude, target_datum='WGS84'):
	utm_zone = int((longitude + 180) / 6) + 1
	is_northern = latitude >= 0

	proj_wgs84 = Proj(proj='latlong', datum=target_datum)  # In example, WGS84 coordinate system
	proj_utm = Proj(proj='utm', zone=utm_zone, datum=target_datum, south=not is_northern)
	easting, northing = transform(proj_wgs84, proj_utm, longitude, latitude)

	return easting, northing, utm_zone

def extrude_polygon(poly, height, transform_utm = True, offset_x=4171084.250000, offset_y=302905.000000):   # TBD. 
	"""
	Extrude a 2D polygon to a 3D polygon with specified height.
	"""
	x, y = poly.exterior.coords.xy

	if transform_utm:
		for i in range(len(x)):
			y[i], x[i], utm_zone = latlon_to_utm(y[i], x[i])
			x[i] -= offset_x
			y[i] -= offset_y
	else:
		latlon_height_scale = 1.0 / 111111.0 # 1m = 1/111111 degree in WGS84
		height = height * latlon_height_scale

	coords = np.array([x, y])
	points_2d = coords.T  # shape (N, 2)
	N = len(points_2d)

	points_3d = np.pad(points_2d, [(0, 0), (0, 1)])  # shape (N, 3)
	face = [N + 1] + list(range(N)) + [0]  # cell connectivity for a single cell
	polygon = pv.PolyData(points_3d, faces=face)

	obj = polygon.extrude((0, 0, height), capping=True)   # extrude along z and plot
	
	return obj

def extrude_geojson(geometry_mapping, input_geojson, base_offset):
	building_metadata = geometry_mapping

	gdf = gpd.read_file(input_geojson)

	# Extrude each polygon in the GeoDataFrame
	features = []
	for index, row in tqdm(gdf.iterrows()):
		feature = {'properties': []}
		feature['properties'] = {}
		for key, value in row.items():
			if key == 'geometry':
				continue
			feature['properties'][key] = value

		gnd_storey_name = building_metadata['ground_storey']
		ground_storey = feature['properties'][gnd_storey_name]
		ugr_storey_name = building_metadata['underground_storey']
		underground_storey = feature['properties'][ugr_storey_name]
		storey_height = building_metadata['storey_height']
		building_height = (ground_storey + underground_storey) * storey_height
		underground_height = underground_storey * storey_height

		geometry = row['geometry']
		building_meshes = []
		if isinstance(geometry, Polygon):
			building = extrude_polygon(geometry, building_height)
			building.translate((0., 0., -underground_height), inplace=True)
			building_meshes.append(building)
		elif isinstance(geometry, MultiPolygon):
			for p in geometry.geoms:
				building = extrude_polygon(p, building_height)
				building.translate((0., 0., -underground_height), inplace=True)
				building_meshes.append(building)

		feature['geometry'] = building_meshes
		features.append(feature)

	# extruded_gdf = gpd.GeoDataFrame(geometry=extruded_polygons, crs=gdf.crs)
	# extruded_gdf.to_file(output_geojson, driver='GeoJSON')

	return features

def save_mesh_excel(features, out_folder):
	index = 0
	for feature in features:
		meshes = feature['geometry']
		for mesh in meshes:
			index += 1
			out_fname = f'{out_folder}/building_{index}.obj' # ply'
			mesh.save(out_fname)	

	# save excel file including properties of feature in features
	with open(f'{out_folder}/building_properties.csv', 'w') as f:
		for index, feature in enumerate(features):
			properties = feature['properties']
			if index == 0:
				header = 'ID,'
				for key, value in properties.items():
					header += f'{key},'
				f.write(f'{header}\n')
			record = f'{index},'
			for key, value in properties.items():
				record += f'{value},'
			f.write(f'{record}\n')
			
def visualize_geojson(geojson_path):
	layer = pdk.Layer(
		'PolygonLayer',
		data=geojson_path,
		get_polygon='geometry.coordinates',
		get_fill_color=[255, 0, 0, 255],
		extruded=True,
		get_elevation='properties.Z'
	)

	view_state = pdk.ViewState(latitude=0, longitude=0, zoom=2)
	deck = pdk.Deck(layers=[layer], initial_view_state=view_state)
	deck.show()

def load_LoD_mapping_file(mapping_file):
	mapping = None
	with open(mapping_file) as f:
		mapping = json.load(f)
	
	return mapping

def test_mapping_file():
	mapping_file['geometry'] = []
	for i in range(0, 10):
		for j in range(0, 10):
			offset = [random.uniform(i * 30.0, i * 40.0), random.uniform(j * 30.0, j * 40), 0.0]
			height = random.uniform(4.0, 30.0)

			footprint = {
				"input": "input.geojson",
				"offset": offset,
				"base_height": 0.0,
				"height": height,
				"output": "output.ply"
			}
			mapping_file['geometry'].append(footprint)

	return mapping_file

def mapping(mapping_file, show_flag=False):
	mapping_file = load_LoD_mapping_file(mapping_file)

	start_time = time.time()  # Start time logging

	objects = []
	for g in mapping_file['geometry']:
		inp = g['input']
		base_offset = g['base_offset']
		features = extrude_geojson(g, inp, base_offset)
		output_folder = g['output']
		if os.path.exists(output_folder) == False:
			os.mkdir(output_folder)
		save_mesh_excel(features, output_folder)
		objects.extend(features)


	end_time = time.time()  # End time logging
	logger.info(f"LoD mapping execution time: {end_time - start_time:.4f} seconds")

	if show_flag:
		# 3D view
		p = pv.Plotter()
		camera = pv.Camera()
		p.camera = camera
		p.camera.position = (0.0, 0.0, 200.0)
		p.camera.focal_point = (0.0, 0.0, 0.0)
		p.camera.up = (0.0, 1.0, 0.0)

		# zoom extents
		p.reset_camera() # shortcut key 'v' maximizes the view

		for obj in objects:
			meshes = obj['geometry']
			properties = obj['properties']

			''' 
			if re.search('고양종합터미널', properties['BLDG_NM']):
				c = (1.0, 0.2, 0.2)
			elif re.search('국민체육센타', properties['BLDG_NM']):
				c = (0.2, 1.0, 0.2)
			else:
				c = (0.5, 0.5, 0.5)
			''' 
			c = (random.uniform(0.3, 1), random.uniform(0.3, 1), random.uniform(0.2, 0.3))
			for mesh in meshes:
				p.add_mesh(mesh, smooth_shading=False, color=c)
				
		p.show_axes()
		# background color is black
		p.background_color = 'black'

		p.reset_camera()
		p.show(title='City 3D buildings viewer') 


if __name__ == '__main__':
	mapping('lod_all_mapping.json')