import os, sys, argparse, json, time, datetime, logging, re, csv, random, string
import ifcopenshell
from tqdm import tqdm

# The xsdata-generated CityGML dataclasses (citygml_parser) are an optional,
# heavy dependency.  Import them lazily so the IFC-parsing / JSON-dump helpers in
# this module work even when xsdata is not installed.
try:
    from citygml_parser import *  # noqa: F401,F403
    from xsdata.formats.dataclass.parsers import XmlParser  # noqa: F401

    _HAVE_CITYGML = True
except Exception:  # pragma: no cover - optional dependency
    _HAVE_CITYGML = False

class Property:
	def __init__(self):
		self.name = ""
		self.value = ""
		self.data_type = ""

class PropertySet:
	def __init__(self):
		self.pset = []

class Object:
	def __init__(self):
		self.name = ""
		self.guid = ""
		self.description = ""

class Element(Object):
	def __init__(self):
		super().__init__()
		self.pset = None
		self.geometries = []
		self.relationships = []
		self.geometries = []  # List of Geometry objects

class Geometry:
	def __init__(self):
		self.type = ""
		self.points = []
		# Members for IfcExtrudedAreaSolid
		self.swept_area = None
		self.extruded_direction = None
		self.depth = None
		self.position = None
		# General geometry members
		self.items = []
		self.context = None

class Relationship(object):
	def __init__(self):
		self.type = ""
		self.relating_property_definition = None
		self.related_objects = []

class Model(object):
    def __init__(self):
        self.elements = []
        self.relationships = []

    def add(self, e):
        self.elements.append(e)

def parse_ifc_file(ifc_file):
	# Initialize the model
	model = Model()

	# Load the IFC file using ifcopenshell
	try:
		ifc_file = ifcopenshell.open(ifc_file)
		if not ifc_file:
			raise Exception(f"Failed to load IFC file: {ifc_file}")
		print(f"Successfully loaded IFC file: {ifc_file}")

		# Enumerate element objects in the IFC model
		elements = ifc_file.by_type("IfcElement")
		print(f"Found {len(elements)} elements in the IFC model.")

		for element in tqdm(elements, desc="Processing elements"):
			obj = Element()
			obj.name = element.Name if hasattr(element, "Name") else ""
			obj.guid = element.GlobalId if hasattr(element, "GlobalId") else ""
			obj.description = element.Description if hasattr(element, "Description") else ""
			model.add(obj)

			# Retrieve property sets and properties for the element
			if hasattr(element, "IsDefinedBy") == False:
				continue
			for rel in element.IsDefinedBy:
				if rel.is_a("IfcRelDefinesByProperties") and hasattr(rel, "RelatingPropertyDefinition"):
					prop_set = rel.RelatingPropertyDefinition
					if prop_set.is_a("IfcPropertySet"):
						pset = PropertySet()
						for prop in prop_set.HasProperties:
							property_obj = Property()
							property_obj.name = prop.Name if hasattr(prop, "Name") else ""
							property_obj.value = prop.NominalValue.wrappedValue if hasattr(prop, "NominalValue") else ""
							property_obj.data_type = type(prop.NominalValue).__name__ if hasattr(prop, "NominalValue") else ""
							pset.pset.append(property_obj)
						obj.pset = pset

			# Retrieve geometries (representations) for the element
			if hasattr(element, "Representation") and element.Representation:
				representations = element.Representation.Representations
				obj.geometries = []
				for representation in representations:
					if hasattr(representation, "Items"):
						for item in representation.Items:
							geometry = Geometry()
							geometry.type = item.is_a()
							
							# Handle IfcExtrudedAreaSolid specifically
							if item.is_a("IfcExtrudedAreaSolid"):
								geometry.swept_area = item.SweptArea if hasattr(item, "SweptArea") else None
								geometry.extruded_direction = item.ExtrudedDirection if hasattr(item, "ExtrudedDirection") else None
								geometry.depth = item.Depth if hasattr(item, "Depth") else None
								geometry.position = item.Position if hasattr(item, "Position") else None
							elif item.is_a("IfcPolyline"):
								geometry.points = item.Points
							else:
								pass
							
							# Store the original item reference
							geometry.items.append(item)
							
							obj.geometries.append(geometry)

			# Retrieve relationships for the element
			if hasattr(element, "IsDefinedBy"):
				obj.relationships = []
				for rel in element.IsDefinedBy:
					relationship_obj = Relationship()
					relationship_obj.type = rel.is_a()
					if hasattr(rel, "RelatingPropertyDefinition"):
						relationship_obj.relating_property_definition = rel.RelatingPropertyDefinition
					if hasattr(rel, "RelatedObjects"):
						relationship_obj.related_objects = rel.RelatedObjects
					obj.relationships.append(relationship_obj)

	except Exception as e:
		print(f"Error loading IFC file: {e}")
		sys.exit(1)

	return model

def dump_ifc_model(model, output_citygml_fname):
	# Convert model to dictionary for JSON serialization
	model_dict = {
		"elements": [],
		"relationships": []
	}

	for element in model.elements:
		try:
			element_dict = {
				"name": element.name,
				"guid": element.guid,
				"description": element.description,
				"geometries": [],
				"relationships": []
			}
			
			# Serialize geometries
			for geometry in element.geometries:
				try:
					geometry_dict = {
						"type": geometry.type,
						"points": [str(point) for point in geometry.points] if geometry.points else [],
						"swept_area": str(geometry.swept_area) if geometry.swept_area else None,
						"extruded_direction": str(geometry.extruded_direction) if geometry.extruded_direction else None,
						"depth": str(geometry.depth) if geometry.depth else None,
						"position": str(geometry.position) if geometry.position else None,
						"items": [str(item) for item in geometry.items] if geometry.items else [],
						"context": str(geometry.context) if geometry.context else None
					}
					element_dict["geometries"].append(geometry_dict)
				except Exception as e:
					print(f"Warning: Skipping geometry due to serialization error: {e}")
					continue
			
			# Add property set if it exists
			if element.pset:
				element_dict["pset"] = []
				for prop in element.pset.pset:
					try:
						prop_dict = {
							"name": prop.name,
							"value": str(prop.value),
							"data_type": prop.data_type
						}
						element_dict["pset"].append(prop_dict)
					except Exception as e:
						print(f"Warning: Skipping property due to serialization error: {e}")
						continue
			
			# Add relationships
			for rel in element.relationships:
				try:
					rel_dict = {
						"type": rel.type,
						"relating_property_definition": str(rel.relating_property_definition) if rel.relating_property_definition else None,
						"related_objects": [str(obj) for obj in rel.related_objects]
					}
					element_dict["relationships"].append(rel_dict)
				except Exception as e:
					print(f"Warning: Skipping relationship due to serialization error: {e}")
					continue
			
			model_dict["elements"].append(element_dict)
		except Exception as e:
			print(f"Warning: Skipping element due to serialization error: {e}")
			continue

	# Write to JSON file
	json_output_fname = output_citygml_fname.replace('.gml', '_bim.json')
	with open(json_output_fname, 'w', encoding='utf-8') as f:
		json.dump(model_dict, f, indent=2, ensure_ascii=False)

	print(f"Model dumped to JSON file: {json_output_fname}")
	return model_dict

def convert_bim_to_citygml(model, output_citygml_fname):
	# Initialize CityGML model
	if not _HAVE_CITYGML:
		raise RuntimeError(
			"CityGML serialisation requires 'xsdata' and the generated "
			"citygml_parser module. Install with: pip install xsdata"
		)
	from xsdata.formats.dataclass.context import XmlContext
	from xsdata.formats.dataclass.serializers import XmlSerializer
	from xsdata.formats.dataclass.serializers.config import SerializerConfig
	from pathlib import Path
	
	# Create CityGML model structure
	city_model = CityModel()
	city_objects = []
	
	# Process each BIM element and convert to CityGML building objects
	for element in model.elements:
		try:
			# Create a Building object for each BIM element
			building = Building()
			
			# Set basic building properties
			if element.guid:
				building.id = f"bim_{element.guid}"
			else:
				building.id = f"bim_element_{len(city_objects)}"
			
			if element.name:
				building.name = [StringOrRef(value=element.name)]
			
			if element.description:
				building.description = [StringOrRef(value=element.description)]
			
			# Process geometries and create boundary surfaces
			boundaries = []
			
			for geometry in element.geometries:
				try:
					# Create boundary surfaces based on geometry type
					if geometry.type == "IfcExtrudedAreaSolid":
						# Create wall surfaces for extruded solids
						wall_surface = create_wall_surface_from_geometry(geometry, len(boundaries))
						if wall_surface:
							boundaries.append(BoundaryProperty(wall_surface=wall_surface))
					
					elif geometry.type == "IfcPolyline":
						# Create surfaces from polylines
						surface = create_surface_from_polyline(geometry, len(boundaries))
						if surface:
							boundaries.append(BoundaryProperty(wall_surface=surface))
				
				except Exception as e:
					print(f"Warning: Failed to process geometry {geometry.type}: {e}")
					continue
			
			# Add default ground surface if no boundaries created
			if not boundaries:
				ground_surface = create_default_ground_surface()
				boundaries.append(BoundaryProperty(ground_surface=ground_surface))
			
			building.boundary = boundaries
			
			# Create city object member
			city_object_member = CityObjectMember(building=building)
			city_objects.append(city_object_member)
			
		except Exception as e:
			print(f"Warning: Failed to convert element {element.name}: {e}")
			continue
	
	# Set city object members
	city_model.city_object_member = city_objects
	
	# Write CityGML file
	try:
		config = SerializerConfig(indent="  ", pretty_print=True)
		context = XmlContext()
		serializer = XmlSerializer(context=context, config=config)
		
		# Define namespace map for CityGML 3.0
		namespace_map = {
			"": "http://www.opengis.net/citygml/3.0",
			"con": "http://www.opengis.net/citygml/construction/3.0", 
			"bldg": "http://www.opengis.net/citygml/building/3.0",
			"gml": "http://www.opengis.net/gml/3.2",
			"xsi": "http://www.w3.org/2001/XMLSchema-instance",
			"xlink": "http://www.w3.org/1999/xlink"
		}
		
		xml_output = serializer.render(city_model, ns_map=namespace_map)
		
		path = Path(output_citygml_fname)
		with path.open("w", encoding='utf-8') as fp:
			fp.write(xml_output)
		
		print(f"CityGML file successfully created: {output_citygml_fname}")
		
	except Exception as e:
		print(f"Error writing CityGML file: {e}")

def create_wall_surface_from_geometry(geometry, surface_id):
	"""Create a WallSurface from BIM geometry"""
	try:
		wall_surface = WallSurface()
		wall_surface.id = f"wall_surface_{surface_id}"
		
		# Create basic polygon geometry if we have enough information
		if hasattr(geometry, 'swept_area') and geometry.swept_area:
			# For extruded area solids, create a simple rectangular wall
			multi_surface = create_simple_wall_geometry()
			if multi_surface:
				wall_surface.lod2_multi_surface = SurfacePropertyType(multi_surface=multi_surface)
		
		return wall_surface
		
	except Exception as e:
		print(f"Error creating wall surface: {e}")
		return None

def create_surface_from_polyline(geometry, surface_id):
	"""Create a surface from polyline geometry"""
	try:
		wall_surface = WallSurface()
		wall_surface.id = f"polyline_surface_{surface_id}"
		
		# Create basic surface geometry
		multi_surface = create_simple_wall_geometry()
		if multi_surface:
			wall_surface.lod2_multi_surface = SurfacePropertyType(multi_surface=multi_surface)
		
		return wall_surface
		
	except Exception as e:
		print(f"Error creating surface from polyline: {e}")
		return None

def create_default_ground_surface():
	"""Create a default ground surface"""
	try:
		ground_surface = GroundSurface()
		ground_surface.id = "default_ground_surface"
		
		# Create a simple square ground surface
		multi_surface = MultiSurface()
		polygon = Polygon()
		polygon.id = "ground_polygon"
		
		# Create exterior linear ring with simple coordinates
		linear_ring = LinearRing()
		linear_ring.id = "ground_ring"
		
		# Simple 10x10 square at ground level
		pos_list = PosList()
		pos_list.value = [0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0, 10.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0]
		pos_list.srs_dimension = 3
		linear_ring.pos_list = pos_list
		
		exterior = AbstractRingPropertyType(linear_ring=linear_ring)
		polygon.exterior = exterior
		
		surface_member = SurfaceMemberType(polygon=polygon)
		multi_surface.surface_member = [surface_member]
		
		ground_surface.lod2_multi_surface = SurfacePropertyType(multi_surface=multi_surface)
		
		return ground_surface
		
	except Exception as e:
		print(f"Error creating default ground surface: {e}")
		return None

def create_simple_wall_geometry():
	"""Create a simple wall geometry"""
	try:
		multi_surface = MultiSurface()
		polygon = Polygon()
		polygon.id = "wall_polygon"
		
		# Create exterior linear ring
		linear_ring = LinearRing()
		linear_ring.id = "wall_ring"
		
		# Simple rectangular wall (5 points to close the rectangle)
		pos_list = PosList()
		pos_list.value = [0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 5.0, 0.0, 3.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0]
		pos_list.srs_dimension = 3
		linear_ring.pos_list = pos_list
		
		exterior = AbstractRingPropertyType(linear_ring=linear_ring)
		polygon.exterior = exterior
		
		surface_member = SurfaceMemberType(polygon=polygon)
		multi_surface.surface_member = [surface_member]
		
		return multi_surface
		
	except Exception as e:
		print(f"Error creating simple wall geometry: {e}")
		return None


def main(input_ifc_fname, output_citygml_fname):
	model = parse_ifc_file(input_ifc_fname)
	dump_ifc_model(model, output_citygml_fname)
	convert_bim_to_citygml(model, output_citygml_fname)

if __name__ == "__main__":
	main("./sample_file/duplex_apartment.ifc", "output_citygml.gml")
