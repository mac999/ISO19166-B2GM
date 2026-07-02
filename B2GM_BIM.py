import os, sys, argparse, json, time, datetime, logging, requests, re, csv, random, string
import ifcopenshell, ifcopenshell.api
import B2GM_property, B2GM_model
from tqdm import tqdm


class BIM(B2GM_model.model):
    def parse(self, fname):
        self.model_data = ifcopenshell.open(fname)

        # enumerate all the nodes in the dataset using ifcopenshell
        objects = []

        element_types = [
            "IfcSite",
            "IfcSpace",
            "IfcWall",
            "IfcDoor",
            "IfcWindow",
            "IfcCovering",
            "IfcBuildingElementPart",
            "IfcSlab",
            "IfcBeam",
            "IfcColumn",
            "IfcBuildingElementProxy",
            "IfcBuildingStorey",
            "IfcWallStandardCase",
            "IfcMember",
            "IfcSpace",
            "IfcStair",
            "IfcRailing",
            "IfcColumn",
            "IfcBuilding"
        ]

        # products = dataset.by_type()
        for product in self.model_data:
            obj_type = product.is_a()
            if obj_type not in element_types:
                continue

            try:
                psets = {}
                if product.IsDefinedBy == None:
                    continue

                # property set
                for relationship in product.IsDefinedBy:
                    if relationship.is_a("IfcRelDefinesByProperties") == False:
                        continue
                    if (
                        relationship.RelatingPropertyDefinition.is_a(
                            "IfcPropertySet"
                        )
                        == False
                    ):
                        continue

                    pset = relationship.RelatingPropertyDefinition
                    props = {}
                    for property in pset.HasProperties:
                        if property.is_a("IfcPropertySingleValue") == False:
                            continue
                        props[property.Name] = (
                            property.NominalValue.wrappedValue
                        )
                    psets[pset.Name] = props


                object = {}
                object["name"] = obj_type
                object["code"] = obj_type
                # stable IFC class, never overwritten by a "name" property below;
                # used by element (EM) and LoD (LM) mapping to match rules.
                object["ifc_type"] = obj_type
                object["type"] = "struct"
                product = self.model_data.by_guid(product.GlobalId)
                object["GUID"] = product.GlobalId
                object["pset"] = {}
                for psets_key in psets:
                    props = psets[psets_key]
                    object["pset"][psets_key] = {}
                    for key in props:
                        value = props[key]
                        if key == "9_Specification-Volume":
                            key.lower()
                        if key.lower() == "name":
                            object["name"] = value
                            object["code"] = value
                        else:
                            object["pset"][psets_key][key] = value

                objects.append(object)
            except Exception as e:
                print(e)
                pass

        try:
            merged_objects = {}
            for obj in tqdm(objects):
                try:
                    GUID = obj["GUID"]
                    if GUID in merged_objects:
                        merged_objects[GUID]["pset"].update(obj["pset"])
                    else:
                        merged_objects[GUID] = obj.copy()
                except Exception as e:
                    print(e)
                    pass

            merged_objects_list = list(merged_objects.values())
            objects = merged_objects_list
        except Exception as e:
            print(e)
            pass

        return objects


def test():
    bim = BIM()
    bim.parse("test.ifc")


if __name__ == "__main__":
    test()
