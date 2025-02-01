"""
CityGML parser example to read and write CityGML file.

Author:
    Taewook Kang (laputa99999@gmail.com)

Date:
    2025-01-02
"""
from citygml_parser import *
from xsdata.formats.dataclass.parsers import XmlParser

# read CityGML file
parser = XmlParser()
model = parser.parse("./sample_file/1_SimpleBuilding/CityGML_3.gml")
print(model)

# write CityGML file
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from pathlib import Path

config = SerializerConfig(indent="  ")
context = XmlContext()
serializer = XmlSerializer()
serializer = XmlSerializer(context=context, config=config)

path = Path("CityGML_3_output.gml")
with path.open("w") as fp:
    serializer.write(fp, model)
