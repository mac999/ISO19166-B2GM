"""Shared pytest fixtures for the ISO 19166 B2GM test suite."""

import os
import sys

import pytest

# Make the project modules importable regardless of the pytest invocation dir.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SAMPLE_IFC = os.path.join(ROOT, "sample_file", "duplex_apartment.ifc")


@pytest.fixture(scope="session")
def project_root():
    return ROOT


@pytest.fixture(scope="session")
def sample_ifc():
    """Absolute path to the bundled sample IFC (skips tests when missing)."""
    if not os.path.exists(SAMPLE_IFC):
        pytest.skip(f"sample IFC not available: {SAMPLE_IFC}")
    return SAMPLE_IFC


@pytest.fixture
def bim_objects():
    """A small set of BIM objects shaped like B2GM_BIM.BIM.parse() output."""
    return [
        {
            "name": "IfcBuilding",
            "code": "IfcBuilding",
            "ifc_type": "IfcBuilding",
            "type": "struct",
            "GUID": "bldg-0001",
            "pset": {"Pset_BuildingCommon": {"NumberOfStoreys": 4, "IsLandmarked": "F"}},
        },
        {
            "name": "Basic Wall",
            "code": "Basic Wall",
            "ifc_type": "IfcWallStandardCase",
            "type": "struct",
            "GUID": "wall-0001",
            "pset": {"Pset_WallCommon": {"IsExternal": "T", "Height": 3.0}},
        },
        {
            "name": "IfcBuildingStorey",
            "code": "IfcBuildingStorey",
            "ifc_type": "IfcBuildingStorey",
            "type": "struct",
            "GUID": "storey-0001",
            "pset": {},
        },
    ]
