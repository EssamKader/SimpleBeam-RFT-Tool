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
  column OR BEAM, used by the rotation-aware support-width path and, since
  issue #18's review, by the beam's own section width and centroid datum.
  The projection math is tested; the extraction step is not. If the real API
  returns already-transformed ``Solid``s instead, both datum paths fall back
  to the world AABB and the rotated-beam case regresses silently.
- ``Transform.OfPoint(XYZ) -> XYZ`` and ``Transform.BasisZ``/``Origin``,
  used to map a local bounding-box centre to world space
  (``beam_section_centre_offsets``). Assumed to be the standard affine
  mapping; not confirmed against a live host.
- ``Rebar.GetShapeDrivenAccessor() -> RebarShapeDrivenAccessor`` and
  ``RebarShapeDrivenAccessor.SetLayoutAsMaximumSpacing(spacing, arrayLength,
  barsOnNormalSide, includeFirstBar, includeLastBar)``. Assumed from
  docs/research/revit-api-strategy.md's documentation-only research (issue
  #18, S5 stirrups); no live-host confirmation of the accessor's exact
  parameter order, or that `GetShapeDrivenAccessor` is even the correct
  accessor name for a `CreateFromCurves`-built stirrup (vs. a distinct
  accessor for shape-driven vs. free-form rebar).
- ``RebarStyle.StirrupTie`` and ``RebarHookType`` (angle/multiplier-bearing
  hook object passed to `Rebar.CreateFromCurves`). Whether
  `RebarStyle.StirrupTie` actually permits a 180-degree hook is the
  load-bearing unverified item named in CONTEXT.md -- this fake does not
  and cannot validate that; it only lets `rft.revit.stirrups` import and
  run under CPython.
- ``Wall.Width`` (issue #15, S2) -- assumed to be a read-only property
  returning the wall's total thickness directly in internal units (feet).
  Not confirmed against a live host; this fake only carries whatever a
  test assigns.
- ``BuiltInCategory.OST_Walls`` / ``OST_StructuralFraming`` as valid
  ``FilteredElementCollector.OfCategory`` arguments for support detection
  (issue #15, S2) -- assumed to exist and behave like ``OST_StructuralColumns``
  already did; not newly confirmed here.
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
    OST_Walls = object()
    OST_StructuralFraming = object()


class FakeFilteredElementCollector(object):
    """Test bodies monkeypatch ``_ITEMS`` per scenario.

    ``OfCategory`` filters ``_ITEMS`` by each item's own ``_category``
    attribute when one is set on the collector; items with no ``_category``
    attribute (the pre-#15 test bodies) match ANY category, preserving the
    original permissive behaviour those tests relied on.
    """

    _ITEMS = []

    def __init__(self, doc):
        self._doc = doc
        self._category = None

    def OfCategory(self, cat):
        self._category = cat
        return self

    def OfClass(self, _cls):
        return self

    def WhereElementIsNotElementType(self):
        return self

    def __iter__(self):
        if self._category is None:
            return iter(FakeFilteredElementCollector._ITEMS)
        return iter(
            item for item in FakeFilteredElementCollector._ITEMS
            if getattr(item, "_category", self._category) is self._category
        )


class FakeRebarHostData(object):
    """Replaced wholesale (monkeypatched) per test scenario."""

    @staticmethod
    def GetRebarHostData(_element):
        raise NotImplementedError("monkeypatch per test")


class FakeRebarStyle(object):
    Standard = object()
    StirrupTie = object()


class FakeRebarHookOrientation(object):
    Left = object()


class FakeRebarHookType(object):
    """SHAPE UNVERIFIED -- stand-in for `Autodesk.Revit.DB.Structure.
    RebarHookType`. Real hook angle/multiplier live on the Revit-side
    object; this fake only carries whatever a test assigns for assertion
    purposes and proves nothing about whether StirrupTie permits 180 deg."""

    def __init__(self, angle_deg=None):
        self.angle_deg = angle_deg


class FakeRebarShapeDrivenAccessor(object):
    """SHAPE UNVERIFIED -- see tests/fake_revit_api.py module header."""

    def __init__(self):
        self.calls = []

    def SetLayoutAsMaximumSpacing(self, spacing, array_length, bars_on_normal_side,
                                   include_first_bar, include_last_bar):
        self.calls.append(
            {
                "spacing": spacing,
                "array_length": array_length,
                "bars_on_normal_side": bars_on_normal_side,
                "include_first_bar": include_first_bar,
                "include_last_bar": include_last_bar,
            }
        )


class FakeRebarInstance(object):
    """SHAPE UNVERIFIED -- stand-in for the `Rebar` element returned by
    `CreateFromCurves`. Real return type/members not confirmed; this only
    records constructor args and hands back a fresh accessor per call."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self._accessor = FakeRebarShapeDrivenAccessor()

    def GetShapeDrivenAccessor(self):
        return self._accessor


class FakeRebar(object):
    @staticmethod
    def CreateFromCurves(*args, **kwargs):
        return FakeRebarInstance(*args, **kwargs)


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


class FakeWall(object):
    """SHAPE UNVERIFIED -- stand-in for `Autodesk.Revit.DB.Wall`, used only
    so ``isinstance(support, Wall)`` (rft.revit.geometry.
    support_width_along_axis_mm, issue #15/S2) can be exercised under
    CPython. Real wall subclassing/`Width` semantics not confirmed -- see
    tests/fake_revit_api.py header."""

    def __init__(self, width_internal, id_value=None, location=None):
        self.Width = width_internal
        self.Id = id_value
        self.Location = location

    def get_BoundingBox(self, _view):
        return None


class FakeGeometryInstance(object):
    """Stand-in for `Autodesk.Revit.DB.GeometryInstance` -- only used so
    `rft.revit.geometry` (which imports the real type at module scope for
    the rotation-aware column bounding box, issue #14 review finding #5)
    remains importable under the fake environment.

    Exercised by tests/test_geometry.py for both the column support-width
    path and the beam section datum (issue #18 review), but only from the
    ``GetBoundingBox()``/``Transform`` pair onward: whether a real host
    hands back a GeometryInstance at all cannot be mocked meaningfully
    (see docs/verification/s5-stirrups.md).
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
    db.Wall = FakeWall
    db.Structure = structure

    structure.RebarHostData = FakeRebarHostData
    structure.RebarStyle = FakeRebarStyle
    structure.RebarHookOrientation = FakeRebarHookOrientation
    structure.Rebar = FakeRebar
    structure.RebarBarType = FakeRebarBarType
    structure.RebarFaceType = FakeRebarFaceType
    structure.RebarHookType = FakeRebarHookType

    revit_pkg.DB = db
    autodesk_pkg.Revit = revit_pkg

    sys.modules["Autodesk"] = autodesk_pkg
    sys.modules["Autodesk.Revit"] = revit_pkg
    sys.modules["Autodesk.Revit.DB"] = db
    sys.modules["Autodesk.Revit.DB.Structure"] = structure
