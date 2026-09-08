"""Installs minimal fake ``Autodesk.Revit.DB`` / ``Autodesk.Revit.DB.Structure``
modules into ``sys.modules`` so ``rft.revit.*`` (which imports the real
Revit API at module scope) can be imported and exercised under plain
CPython.

This is the mechanism behind the mock-object verification tests
(``test_mock_revit_adapter.py``) required by CONTEXT.md: it runs the actual
adapter source, not a re-implementation of its logic, against stand-in
Revit types.

WHAT THESE FAKES DO NOT PROVE
-----------------------------
These stand-ins are written to match the API shape the adapter *assumes*.
A passing test therefore proves the adapter's **logic** is self-consistent —
it does **not** validate that the real Revit API has those members, those
signatures, or those return types. If an assumed shape is wrong, these tests
pass and the tool still throws on its first real run.

Every fake standing in for an API whose shape is not documentation-confirmed
must carry an inline ``SHAPE UNVERIFIED`` note naming what is assumed, so a
green suite is never mistaken for API validation.

Currently ``SHAPE UNVERIFIED``:

- ``RebarHostData.GetFaces(RebarFaceType) -> list`` and
  ``GetCoverType(face) -> ElementId``. Documentation research instead found
  ``GetExposedFaces() -> IList<Reference>`` and
  ``GetCoverType(Reference) -> RebarCoverType``, i.e. the whole face-lookup
  shape may be wrong, not just the face argument. Tracked for correction
  against a live host — see ``docs/verification/s1-tracer-bullet.md``.
- ``FamilyInstance.get_Geometry() -> GeometryInstance`` for a structural
  column, used by the rotation-aware support-width path. The projection math
  is tested; the extraction step is not.
"""

import math
import sys
import types


class FakeXYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = x, y, z

    def __sub__(self, other):
        return FakeXYZ(self.X - other.X, self.Y - other.Y, self.Z - other.Z)

    def __add__(self, other):
        return FakeXYZ(self.X + other.X, self.Y + other.Y, self.Z + other.Z)

    def Normalize(self):
        n = math.sqrt(self.X ** 2 + self.Y ** 2 + self.Z ** 2) or 1.0
        return FakeXYZ(self.X / n, self.Y / n, self.Z / n)

    def Multiply(self, scalar):
        return FakeXYZ(self.X * scalar, self.Y * scalar, self.Z * scalar)

    def Negate(self):
        return FakeXYZ(-self.X, -self.Y, -self.Z)

    def DotProduct(self, other):
        return self.X * other.X + self.Y * other.Y + self.Z * other.Z

    def CrossProduct(self, other):
        return FakeXYZ(
            self.Y * other.Z - self.Z * other.Y,
            self.Z * other.X - self.X * other.Z,
            self.X * other.Y - self.Y * other.X,
        )

    def __eq__(self, other):
        return (self.X, self.Y, self.Z) == (other.X, other.Y, other.Z)


FakeXYZ.BasisZ = FakeXYZ(0.0, 0.0, 1.0)


class FakeLine(object):
    @staticmethod
    def CreateBound(p0, p1):
        return ("Line", p0, p1)


class FakeElementId(object):
    def __init__(self, value=-1):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, FakeElementId) and other.value == self.value


FakeElementId.InvalidElementId = FakeElementId(-1)


class FakeUnitTypeId(object):
    Millimeters = object()


class FakeUnitUtils(object):
    """1 internal unit == 1 foot; 1 foot == 304.8 mm (matches real Revit)."""

    @staticmethod
    def ConvertToInternalUnits(value, _unit_type_id):
        return value / 304.8

    @staticmethod
    def ConvertFromInternalUnits(value, _unit_type_id):
        return value * 304.8


class FakeTransaction(object):
    def __init__(self, doc, name):
        self.doc = doc
        self.name = name
        self.started = False
        self.committed = False
        self.rolled_back = False

    def Start(self):
        self.started = True

    def Commit(self):
        self.committed = True

    def RollBack(self):
        self.rolled_back = True


class FakeBuiltInCategory(object):
    OST_StructuralColumns = object()


class FakeFilteredElementCollector(object):
    """Test bodies monkeypatch ``_ITEMS`` per scenario."""

    _ITEMS = []

    def __init__(self, doc):
        self._doc = doc

    def OfCategory(self, _cat):
        return self

    def OfClass(self, _cls):
        return self

    def WhereElementIsNotElementType(self):
        return self

    def __iter__(self):
        return iter(FakeFilteredElementCollector._ITEMS)


class FakeRebarHostData(object):
    """Replaced wholesale (monkeypatched) per test scenario."""

    @staticmethod
    def GetRebarHostData(_element):
        raise NotImplementedError("monkeypatch per test")


class FakeRebarStyle(object):
    Standard = object()


class FakeRebarHookOrientation(object):
    Left = object()


class FakeRebar(object):
    @staticmethod
    def CreateFromCurves(*args, **kwargs):
        return {"args": args, "kwargs": kwargs}


class FakeRebarBarType(object):
    pass


class FakeRebarFaceType(object):
    Bottom = object()
    Top = object()
    Other = object()
    Exterior = object()
    Interior = object()


class FakeOptions(object):
    pass


class FakeGeometryInstance(object):
    """Stand-in for `Autodesk.Revit.DB.GeometryInstance` -- only used so
    `rft.revit.geometry` (which imports the real type at module scope for
    the rotation-aware column bounding box, issue #14 review finding #5)
    remains importable under the fake environment. Not exercised by any
    test yet: extracting real column geometry cannot be meaningfully
    mocked without a live host (see docs/verification/s1-tracer-bullet.md).
    """

    def __init__(self, local_bbox=None, transform=None):
        self._local_bbox = local_bbox
        self.Transform = transform

    def GetBoundingBox(self):
        return self._local_bbox


def install():
    db = types.ModuleType("Autodesk.Revit.DB")
    structure = types.ModuleType("Autodesk.Revit.DB.Structure")
    revit_pkg = types.ModuleType("Autodesk.Revit")
    autodesk_pkg = types.ModuleType("Autodesk")

    db.XYZ = FakeXYZ
    db.Line = FakeLine
    db.ElementId = FakeElementId
    db.UnitTypeId = FakeUnitTypeId
    db.UnitUtils = FakeUnitUtils
    db.Transaction = FakeTransaction
    db.BuiltInCategory = FakeBuiltInCategory
    db.FilteredElementCollector = FakeFilteredElementCollector
    db.Options = FakeOptions
    db.GeometryInstance = FakeGeometryInstance
    db.Structure = structure

    structure.RebarHostData = FakeRebarHostData
    structure.RebarStyle = FakeRebarStyle
    structure.RebarHookOrientation = FakeRebarHookOrientation
    structure.Rebar = FakeRebar
    structure.RebarBarType = FakeRebarBarType
    structure.RebarFaceType = FakeRebarFaceType

    revit_pkg.DB = db
    autodesk_pkg.Revit = revit_pkg

    sys.modules["Autodesk"] = autodesk_pkg
    sys.modules["Autodesk.Revit"] = revit_pkg
    sys.modules["Autodesk.Revit.DB"] = db
    sys.modules["Autodesk.Revit.DB.Structure"] = structure
