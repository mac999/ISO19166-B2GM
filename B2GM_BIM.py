import os, sys, argparse, json, time, datetime, logging, re, csv, random, string
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

        # attach inter-element relationships (ISO 19166 BM5, UML relationships)
        self._attach_relationships(objects)

        # attach triangulated geometry (world coords) so the GIS side can write
        # renderable CityGML; failures are non-fatal (element kept without geometry)
        self._attach_geometry(objects)

        return objects

    # IFC relationship entity -> (source attr, target attr, UML relationship type,
    # relationship name).  The "source" side is the element the relationship is
    # attached to; the "target" side is the referenced element/material/type.
    # UML types follow B2GM_model.RelationshipType (association/dependency/generalization).
    _REL_HANDLERS = {
        "IfcRelAggregates": ("RelatingObject", "RelatedObjects", "association", "aggregates"),
        "IfcRelContainedInSpatialStructure": ("RelatingStructure", "RelatedElements", "association", "contains"),
        "IfcRelConnectsElements": ("RelatingElement", "RelatedElement", "association", "connects"),
        "IfcRelConnectsPathElements": ("RelatingElement", "RelatedElement", "association", "connects"),
        "IfcRelVoidsElement": ("RelatingBuildingElement", "RelatedOpeningElement", "association", "voids"),
        "IfcRelFillsElement": ("RelatingOpeningElement", "RelatedBuildingElement", "association", "fills"),
        "IfcRelSpaceBoundary": ("RelatingSpace", "RelatedBuildingElement", "association", "space_boundary"),
        "IfcRelAssociatesMaterial": ("RelatedObjects", "RelatingMaterial", "dependency", "material"),
        "IfcRelDefinesByType": ("RelatedObjects", "RelatingType", "generalization", "type"),
    }

    def _attach_relationships(self, objects):
        """Populate ``obj['relationship']`` from the IFC ``IfcRel*`` entities.

        Each record is ``{name, type, related}`` where ``type`` is the UML kind
        (association / dependency / generalization) and ``related`` references the
        target element/material/type (``{type, guid, name}``).  Only relationships
        whose *source* element was exported are attached; the target reference is
        kept even when the target (e.g. a material or opening) is not in the
        exported set.  Best-effort: any relationship that fails to read is skipped.
        """
        by_guid = {o.get("GUID"): o for o in objects if o.get("GUID")}

        def ref_of(entity):
            if entity is None:
                return None
            name = getattr(entity, "Name", None)
            return {
                "type": entity.is_a() if hasattr(entity, "is_a") else "",
                "guid": getattr(entity, "GlobalId", "") or "",
                "name": name if name else (entity.is_a() if hasattr(entity, "is_a") else ""),
            }

        def as_list(value):
            if value is None:
                return []
            return list(value) if isinstance(value, (list, tuple)) else [value]

        try:
            relationships = self.model_data.by_type("IfcRelationship")
        except Exception as exc:
            print("could not enumerate relationships:", exc)
            return

        for rel in relationships:
            handler = self._REL_HANDLERS.get(rel.is_a())
            if handler is None:
                continue
            source_attr, target_attr, uml_type, rel_name = handler
            try:
                sources = as_list(getattr(rel, source_attr, None))
                targets = as_list(getattr(rel, target_attr, None))
                for src in sources:
                    guid = getattr(src, "GlobalId", None)
                    if guid not in by_guid:
                        continue
                    for tgt in targets:
                        ref = ref_of(tgt)
                        if ref is None:
                            continue
                        by_guid[guid].setdefault("relationship", []).append(
                            {"name": rel_name, "type": uml_type, "related": ref}
                        )
            except Exception:
                continue

    def save(self, fname, objects):
        """Serialise parsed BIM objects to JSON per ``B2GM_BIM_model.XSD``.

        The document mirrors the ISO 19166 BIM model UML: a ``BIM_model`` holds
        ``BIM_element`` entries, each with ``relationship`` / ``property_set`` /
        ``runtime`` / ``geometry`` (member order follows the XSD).  The element
        name and GUID are written as the mandatory *system* ``property_set``
        (Table 1, BM4); ``geometry`` carries the B-rep points/faces.
        """
        elements = []
        for o in objects:
            elements.append(
                {
                    "relationship": B2GM_model.relationships_json(o.get("relationship")),
                    "property_set": B2GM_model.element_property_sets_json(o),
                    "runtime": {"type": o.get("ifc_type", o.get("type", ""))},
                    "geometry": B2GM_model.geometry_json(o.get("geometry")),
                }
            )
        document = {"BIM_model": {"BIM_element": elements}}
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(document, f, indent=2, ensure_ascii=False, default=str)
        logging.info("BIM model saved (%d elements) -> %s", len(elements), fname)
        return fname

    def load(self, fname):
        """Load a ``B2GM_BIM_model.XSD`` JSON file written by :meth:`save`.

        Reconstructs the internal object dicts (the same shape :meth:`parse`
        produces: ``name`` / ``code`` / ``ifc_type`` / ``predefined_type`` /
        ``GUID`` / ``pset`` / ``relationship`` / ``geometry``) so a saved model
        can be re-mapped or re-serialised without re-reading the IFC.  Returns the
        list of objects (``round-trip`` safe with :meth:`save`).
        """
        with open(fname, "r", encoding="utf-8") as f:
            document = json.load(f)

        elements = (document.get("BIM_model") or {}).get("BIM_element", [])
        objects = []
        for e in elements:
            system, user = B2GM_model.property_sets_from_json(e.get("property_set"))
            obj = {
                "name": system.get("name", ""),
                "code": system.get("name", ""),
                "ifc_type": (e.get("runtime") or {}).get("type", ""),
                "predefined_type": system.get("predefined_type", ""),
                "type": "struct",
                "GUID": system.get("GUID", ""),
                "pset": user,
                "relationship": e.get("relationship", []),
            }
            geom = B2GM_model.geometry_from_json(e.get("geometry"))
            if geom:
                obj["geometry"] = geom
            objects.append(obj)

        logging.info("BIM model loaded (%d elements) <- %s", len(objects), fname)
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
