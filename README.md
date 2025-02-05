# ISO 19166 - B2GM BIM to GIS Mapping

This project is an ongoing development effort to implement **ISO TC211 TS 19166**, focusing on mapping **Building Information Modeling (BIM) files to GIS formats**. The core functionality allows for extracting, transforming, and exporting BIM elements into GIS-compatible representations, facilitating interoperability between BIM and GIS ecosystems.</br>
<img src="https://github.com/mac999/ISO19166-B2GM/blob/main/doc/fig1.JPG"></img>

## 🚀 Features
- **BIM to GIS Mapping:** Convert **BIM** like IFC, geojson files into **GIS** like CityGML, json or other GIS formats.
- **IFC and [CityGML parsing](https://github.com/mac999/citygml_parser):** Read and Write IFC, CityGML file format using parser.
- **LoD Extrusion:** Extrude 2D building footprints to **3D geometries** using LoD (Level of Detail) specifications.
- **Coordinate System Transformation:** Convert geographic coordinates (WGS84) to projected UTM coordinates.
- **Visualization Support:** Utilize PyVista and PyDeck for 3D rendering of transformed data.

## 🛠 Development Status
This project is **under continuous development**, and features will be incrementally improved over time. Contributions and discussions on BIM-GIS interoperability and ISO 19166 implementations are welcome!

## 📂 Project Structure
```
B2GM_project/
│── B2GM_main.py                # Main script for IFC to GIS transformation
│── B2GM_LM_op_extrude.py       # LoD extrusion and 3D conversion logic
│── LoD1_mapping_example.json   # Example mapping configuration file
```

## 🛠 Installation
Install the required dependencies using **pip**:
```bash
pip install geopandas numpy pyvista pydeck meshio xsdata shapely pyproj tqdm ifcopenshell
```

## ⚙️ Usage
### 1. **LoD Extrusion for 3D GIS Models**
Extrude building footprints from GeoJSON to 3D geometries:
```bash
python B2GM_LM_op_extrude.py goyang_footprint_sample.geojson output_folder LoD1_mapping_example.json
```
<img src="https://github.com/mac999/ISO19166-B2GM/blob/main/doc/fig2.JPG"></img>

### 2. **BIM to GIS Conversion**
Run the main script to process an **IFC** file and generate a **GIS output** (TBD):
```bash
python B2GM_main.py --input duplex_apartment.ifc --output city.gml --pipeline B2GM_example.json
```

## 📌 Configuration
The `LoD1_mapping_example.json` file defines the mapping rules:
```json
{
    "CRS": "EPSG:4326",
    "geometry": [
        {
            "input": "goyang_footprint_sample.geojson",
            "base_offset": [0.0, 0.0, 0.0],
            "ground_storey": "GRO_FLO_CO",
            "underground_storey": "UND_FLO_CO",
            "storey_height": 3.0,
            "output": "./output_all"
        }
    ]
}
```

## Reference
In detail, please refer to below documents. 
- [Development of a Conceptual Mapping Standard to Link Building and Geospatial Information](https://www.mdpi.com/2220-9964/7/5/162)
- [ISO/TS 19166:2021](https://www.iso.org/standard/78899.html)
- [CityGML 3.0 Parser](https://github.com/mac999/citygml_parser)
- [LandXML Parser](https://github.com/mac999/landxml_parser)
- [Py3DTilers: an open-source toolkit to create 3DTiles](https://github.com/VCityTeam/py3dtilers)
- [Technical University of Munich. Prof. Thomas H. Kolbe](https://www.asg.ed.tum.de/gis/unser-team/lehrstuhlangehoerige/prof-thomas-h-kolbe/)
- [CityGML 3.0 Specification XSD](https://github.com/opengeospatial/CityGML-3.0/tree/master)
- [CityGML 3.0 Conceptual Model Encoding in OGC GML 3.2](https://github.com/opengeospatial/CityGML3.0-GML-Encoding/tree/main)
- [CityJSON](https://www.cityjson.org/software/), [Convert GML to JSON](https://github.com/citygml4j/citygml-tools/releases) and [Viewer](https://ninja.cityjson.org/)
- [BIM IFC 파일을 Cesium 디지털트윈 플랫폼에 3D tiles로 가시화하는 방법과 구조](https://daddynkidsmakers.blogspot.com/2024/10/bim-ifc-cesium-3d-tile.html)
- [무료 CityGML 3D 도시모델 뷰어 FZK Viewer 와 도시 시뮬레이션 SimStadt 소개](https://daddynkidsmakers.blogspot.com/2024/10/citygml.html)
- [BIM, GIS 표준 IFC, CityGML 파일 변환 및 정보 추출하기](https://daddynkidsmakers.blogspot.com/2021/09/bim-to-gis.html)

If you're considering XSD parser, refer the below link.
- [lxml](https://github.com/lxml/lxml?tab=readme-ov-file)
- [xsdata](https://github.com/tefra/xsdata) and [manual](https://xsdata.readthedocs.io/en/latest/)
- [xmlschema](https://github.com/sissaschool/xmlschema)
- [generateDS](https://github.com/ricksladkey/generateDS)
- [xsd2xml](https://github.com/miaozn/xsd2xml/blob/master/xsd2xml.py)

If you want to view the GML file, use the below tool. 
- [CityGMLViewer - SimStadt](https://simstadt.hft-stuttgart.de/related-softwares/city-gml-viewer/)

## 📜 License
This project follows an open-source license. See `MIT` for details.

## 📧 Contact
Developed by **Taewook Kang**
For inquiries: laputa99999@gmail.com

