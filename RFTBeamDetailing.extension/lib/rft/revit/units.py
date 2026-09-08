"""The mm <-> Revit-internal-units boundary. The only place a value is
allowed to cross between millimetres (used everywhere in ``rft.core``) and
Revit's internal feet.

Rev 2 section 10.
"""

from Autodesk.Revit.DB import UnitTypeId, UnitUtils


def mm_to_internal(value_mm):
    """mm -> Revit internal units (feet)."""
    return UnitUtils.ConvertToInternalUnits(value_mm, UnitTypeId.Millimeters)


def internal_to_mm(value_internal):
    """Revit internal units (feet) -> mm."""
    return UnitUtils.ConvertFromInternalUnits(value_internal, UnitTypeId.Millimeters)
