"""
CityGML example to list objects.

Author:
	Taewook Kang (laputa99999@gmail.com)

Date:
	2025-02-08

Reference: 
	https://xsdata.readthedocs.io/en/v23.8/api/reference/xsdata.formats.dataclass.parsers.config.ParserConfig.html
"""
import json, argparse
from lxml import etree
from citygml_parser3 import *
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from pathlib import Path
import logging
logging.basicConfig(level=logging.DEBUG)

def main():
	parser = argparse.ArgumentParser(description='CityGML example to list objects.')
	parser.add_argument('--input', type=str, default='./sample/CityGML_3.gml', help='Input CityGML file') # buliding
	args = parser.parse_args()

	config = ParserConfig() 
	parser = XmlParser(config) 
	model = parser.parse(args.input)
	city_objects = model.city_object_member

	for city_object in city_objects:
		building = city_object.building

		print(f'building id: {building.id}')
		print(f'building name: {building.name}')

		try:
			for bound in building.boundary:
				wall = bound.wall_surface
				if wall:
					print(f'wall id: {wall.id}')
				roof = bound.roof_surface
				if roof:
					print(f'roof id: {roof.id}')
				floor = bound.floor_surface
				if floor:
					print(f'floor id: {floor.id}')
				ground = bound.ground_surface
				if ground:
					print(f'ground id: {ground.id}')
				
			if building.lod1_solid:
				print(f'building lod1_solid')
				for sf in building.lod2_solid.solid.exterior.shell.surface_member:
					print(f'surface: {sf.href}')			
			if building.lod2_solid:
				print(f'building lod2_solid')
				for sf in building.lod2_solid.solid.exterior.shell.surface_member:
					print(f'surface: {sf.href}')
			if building.lod3_solid:
				print(f'building lod3_solid')
				for sf in building.lod2_solid.solid.exterior.shell.surface_member:
					print(f'surface: {sf.href}')
			if building.lod4_solid:
				print(f'building lod4_solid')
				for sf in building.lod2_solid.solid.exterior.shell.surface_member:
					print(f'surface: {sf.href}')
		except Exception as e:
			pass

if __name__ == "__main__":
	main()