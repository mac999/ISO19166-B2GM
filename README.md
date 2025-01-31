# ISO 19166 - B2GM BIM to GIS Mapping

This project is an ongoing development effort to implement **ISO TC211 TS 19166**, focusing on mapping **Building Information Modeling (BIM) files to GIS formats**. The core functionality allows for extracting, transforming, and exporting BIM elements into GIS-compatible representations, facilitating interoperability between BIM and GIS ecosystems.

## 🚀 Features
- **BIM to GIS Mapping:** Convert **IFC** files into **CityGML** or other GIS formats.
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
pip install geopandas numpy pyvista pydeck meshio shapely pyproj tqdm ifcopenshell
```

## ⚙️ Usage
### 1. **BIM to GIS Conversion**
Run the main script to process an **IFC** file and generate a **GIS output**:
```bash
python B2GM_main.py --input duplex_apartment.ifc --output city.gml --pipeline B2GM_example.json
```

### 2. **LoD Extrusion for 3D GIS Models**
Extrude building footprints from GeoJSON to 3D geometries:
```bash
python B2GM_LM_op_extrude.py goyang_footprint_sample.geojson output_folder LoD1_mapping_example.json
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

## 📜 License
This project follows an open-source license. See `MIT` for details.

## 📧 Contact
Developed by **Taewook Kang**
For inquiries: laputa99999@gmail.com

