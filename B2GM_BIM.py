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
                # IFC PredefinedType enum (e.g. IfcSlab -> FLOOR/ROOF/BASESLAB),
                # exposed so mapping rules can refine a type, e.g. "IfcSlab.ROOF".
                # NOTDEFINED/USERDEFINED (and missing) carry no useful distinction.
                predefined = getattr(product, "PredefinedType", None)
                predefined = str(predefined) if predefined is not None else ""
                if predefined in ("NOTDEFINED", "USERDEFINED", "NULL"):
                    predefined = ""
                object["predefined_type"] = predefined
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

        # attach triangulated geometry (world coords) so the GIS side can write
        # renderable CityGML; failures are non-fatal (element kept without geometry)
        self._attach_geometry(objects)

        return objects

    def _attach_geometry(self, objects):
        """Populate ``obj['geometry'] = {'verts': [...], 'faces': [...]}`` (flat
        lists, world coordinates in metres) for every object that has an IFC
        shape representation, using ifcopenshell's geometry engine.

        The whole step is best-effort: if the geometry engine is unavailable or a
        single product fails to tessellate, that element is simply left without
        geometry rather than aborting the parse.
        """
        try:
            import ifcopenshell.geom as geom
        except Exception as exc:  # pragma: no cover - geometry engine missing
            print("geometry engine unavailable, skipping geometry:", exc)
            return

        settings = geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)

        for obj in tqdm(objects, desc="geometry"):
            guid = obj.get("GUID")
            if not guid:
                continue
            try:
                product = self.model_data.by_guid(guid)
                if getattr(product, "Representation", None) is None:
                    continue
                shape = geom.create_shape(settings, product)
                verts = list(shape.geometry.verts)   # flat [x,y,z, x,y,z, ...]
                faces = list(shape.geometry.faces)   # flat [i,j,k, i,j,k, ...]
                if verts and faces:
                    obj["geometry"] = {"verts": verts, "faces": faces}
            except Exception:
                # non-representable or failed tessellation -> keep element as-is
                continue


def test():
    bim = BIM()
    bim.parse("test.ifc")


if __name__ == "__main__":
    test()
