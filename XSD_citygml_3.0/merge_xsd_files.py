import os

def merge_xsd_files(input_folder, output_file):
    xsd_files = [f for f in os.listdir(input_folder) if f.endswith(".xsd")]
    
    if not xsd_files:
        print(f"No XSD files found in the directory: {input_folder}")
        return
    
    merged_content = """<?xml version="1.0" encoding="UTF-8"?>\n<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">\n"""
    
    for file_name in xsd_files:
        file_path = os.path.join(input_folder, file_name)
        with open(file_path, "r", encoding="utf-8") as file:
            inside_schema = False
            for line in file:
                if "<schema" in line:
                    inside_schema = True  # Start of schema, ignore it
                    continue
                if "</schema>" in line:
                    inside_schema = False  # End of schema, ignore it
                    continue
                if inside_schema:
                    merged_content += line
    
    merged_content += "</xs:schema>"
    
    with open(output_file, "w", encoding="utf-8") as merged_file:
        merged_file.write(merged_content)

# Run the function to merge XSD files
merge_xsd_files('./XSD_citygml_3.0', 'merged_schema.xsd')
