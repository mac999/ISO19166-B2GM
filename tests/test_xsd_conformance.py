"""Conformance tests: the implementation classes must expose every member of the
ISO 19166 UML structures defined in the ``XSD/`` schemas.

Each ``xs:complexType`` in the XSD files is mapped to a Python class plus the
attribute that realises each of its child ``xs:element`` members.  The test
parses the XSDs directly, so adding/removing an XSD member (or forgetting to
implement one) is caught automatically.
"""

import os
import re

import pytest

import B2GM_element as EM
import B2GM_LM as LM
import B2GM_LM_operators as OP
import B2GM_model as M
import B2GM_PD as PD

XSD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "XSD")


def _parse_xsd(path):
    """Return {complexType_name: [child element names]} from a UTF-16 XSD."""
    txt = open(path, "rb").read().decode("utf-16", "ignore")
    types = {}
    for m in re.finditer(r'<xs:complexType name="([^"]+)">(.*?)</xs:complexType>', txt, re.S):
        types[m.group(1)] = re.findall(r'<xs:element name="([^"]+)"', m.group(2))
    return types


# XSD complexType -> (instance factory, {xsd member name: python attribute}).
# A member mapped to None is intentionally represented structurally elsewhere.
REGISTRY = {
    # --- BIM / GIS conceptual model (B2GM_model.py) --------------------------
    "B-rep": (lambda: M.brep(), {}),
    "property": (lambda: M.property(), {"name": "name", "type": "data_type", "value": "value"}),
    "property_set": (lambda: M.property_set(), {"name": "name", "property": "pset"}),
    "geometry": (lambda: M.geometry(), {"B-rep": "breps"}),
    "geometry2D": (lambda: M.geometry2D(), {}),
    "geometry3D": (lambda: M.geometry3D(), {}),
    "relationship": (lambda: M.relationship(), {"name": "name", "type": "type"}),
    "runtime": (lambda: M.runtime(), {"type": "type"}),
    "LOD": (lambda: M.LOD(), {"name": "name", "geometry": "geometries"}),
    "BIM_element": (lambda: M.element(), {
        "relationship": "relationships", "property_set": "property_sets",
        "runtime": "runtime", "geometry": "geometries"}),
    "GIS_element": (lambda: M.element(), {
        "runtime": "runtime", "LOD": "lods",
        "relationship": "relationships", "property_set": "property_sets"}),
    "BIM_model": (lambda: M.model(), {"BIM_element": "elements"}),
    "GIS_model": (lambda: M.model(), {"GIS_element": "elements"}),
    # --- Element Mapping (B2GM_element.py) -----------------------------------
    "EM_source": (lambda: EM.EM_source(), {"element": "element"}),
    "EM_destination": (lambda: EM.EM_destination(), {"element": "element"}),
    "EM_rule": (lambda: EM.ElementRule("IfcWall", "WallSurface"), {
        "name": "name", "destination": "destination", "PSet_operation": "pset_operation",
        "EM_source": "em_source", "EM_destination": "em_destination"}),
    "EM_ruleset": (lambda: EM.EM_ruleset(), {
        "name": "name", "description": "description",
        "BIM_model_source": "bim_model_source",
        "GIS_model_destination": "gis_model_destination", "EM_rule": "rules"}),
    # --- LoD Mapping (B2GM_LM.py + operators) --------------------------------
    "LM_rule": (lambda: LM.LoDRule(), {"name": "name"}),
    "LM_ruleset": (lambda: LM.LM_ruleset(), {"name": "name", "LM_rule": "rules"}),
    "OBB": (lambda: OP.OBB((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)), {
        "x_direction": "x_direction", "y_direction": "y_direction", "extent": "extent"}),
    "vector3D": (lambda: OP.Vector3D(), {"v": "v"}),
    # --- Perspective Definition (B2GM_PD.py) ---------------------------------
    "PD": (lambda: PD.PerspectiveDefinition(), {
        "name": "name", "BIM_model_destination": "BIM_model_destination",
        "PD_sytle_view": "PD_style_view", "PD_data_view": "PD_data_view",
        "PD_logic_view": "PD_logic_view"}),
    "PD_category": (lambda: PD.PD_category(), {
        "name": "name", "PD_property": "PD_property", "PD_category": "PD_category"}),
    "PD_data_view": (lambda: PD.PD_data_view(), {"PD_element": "PD_element"}),
    "PD_element": (lambda: PD.PD_element(), {"objectGUID": "objectGUID", "PD_category": "PD_category"}),
    "PD_logic_view": (lambda: PD.PD_logic_view(), {
        "external_data_source": "external_data_source", "ETL_module": "ETL_module"}),
    "PD_property": (lambda: PD.PD_property(), {"name": "name", "value": "value", "type": "type"}),
    "PD_property_style": (lambda: PD.PD_property_style(), {
        "category": "category", "property": "property", "formattingOperation": "formattingOperation"}),
    "PD_sytle_view": (lambda: PD.PD_style_view(), {"PD_property_style": "PD_property_style"}),
}

XSD_FILES = ["B2GM_BIM_model", "B2GM_GIS_model", "B2GM_EM", "B2GM_LM", "B2GM_PD"]


def _all_types():
    types = {}
    for name in XSD_FILES:
        path = os.path.join(XSD_DIR, f"{name}.XSD")
        if os.path.exists(path):
            types.update(_parse_xsd(path))  # BIM/GIS overlaps resolve to same members
    return types


def test_every_xsd_type_is_implemented():
    """Every complexType in the schemas must have a mapped implementation class."""
    missing = [t for t in _all_types() if t not in REGISTRY]
    assert not missing, f"XSD complexTypes with no implementation: {sorted(missing)}"


@pytest.mark.parametrize("xsd_file", XSD_FILES)
def test_class_members_match_xsd(xsd_file):
    path = os.path.join(XSD_DIR, f"{xsd_file}.XSD")
    if not os.path.exists(path):
        pytest.skip(f"missing schema: {path}")
    problems = []
    for type_name, members in _parse_xsd(path).items():
        factory, mapping = REGISTRY.get(type_name, (None, {}))
        if factory is None:
            problems.append(f"{type_name}: not implemented")
            continue
        instance = factory()
        for member in members:
            attr = mapping.get(member)
            if attr is None or not hasattr(instance, attr):
                problems.append(f"{type_name}.{member} -> missing attribute {attr!r}")
    assert not problems, "XSD conformance gaps:\n  " + "\n  ".join(problems)
