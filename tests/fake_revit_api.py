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

VERIFIED LIVE (issue #30, Revit 2024, ``RevitAPI 24.3.40.0`` — see issue
#23's live probe) and so REMOVED from the list below:

- ``RebarHostData`` does NOT expose ``GetFaces(RebarFaceType)`` /
  ``GetCoverType(face) -> ElementId`` — that whole shape, including the
  ``RebarFaceType`` enum itself, does not exist. The real shape is
  ``GetExposedFaces() -> IList<Reference>`` and
  ``GetCoverType(Reference) -> RebarCoverType`` (the ``RebarCoverType``
  object itself, not an ``ElementId`` needing a further ``doc.GetElement``
  round trip). ``FakeRebarHostData`` and every scenario-specific host-data
  stub below are now built to this shape.
- ``face.ComputeNormal(UV) -> XYZ`` and
  ``Element.GetGeometryObjectFromReference(Reference) -> Face`` both work
  live and were how the probe recovered each exposed face's normal.
- ``RebarCoverType.CoverDistance`` (internal units) is a real, readable
  property — confirmed live. ``RebarCoverType.Id``/``.Name`` are assumed to
  be the standard ``Element`` members (not specifically probed, but not a
  new assumption either).

Currently ``SHAPE UNVERIFIED``:

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
  hook object passed to `Rebar.CreateFromCurves`). This fake does not and
  cannot validate real `Rebar.CreateFromCurves` acceptance behaviour; it
  only lets `rft.revit.stirrups` import and run under CPython. CONTEXT.md's
  original "does StirrupTie permit 180 deg" load-bearing unknown was
  resolved live for issue #25/#31 (A45): it is the hook's
  `REBAR_HOOK_STYLE` FAMILY that StirrupTie constrains (must be 1 =
  Stirrup/Tie), not any particular angle -- confirmed against Revit 2024.
  See the `REBAR_HOOK_STYLE` entry below for what that live probe did and
  did not confirm about the exact read-back accessor.
- ``Wall.Width`` (issue #15, S2) -- assumed to be a read-only property
  returning the wall's total thickness directly in internal units (feet).
  Not confirmed against a live host; this fake only carries whatever a
  test assigns.
- ``BuiltInCategory.OST_Walls`` / ``OST_StructuralFraming`` as valid
  ``FilteredElementCollector.OfCategory`` arguments for support detection
  (issue #15, S2) -- assumed to exist and behave like ``OST_StructuralColumns``
  already did; not newly confirmed here.
- A SECOND, independently-picked ``OST_StructuralFraming`` neighbour
  (issue #22, S9 continuous-run guard) exposing ``Location.Curve`` the same
  way the beam being detailed does. ``beam_axis_direction``/``beam_endpoints``
  already carried this assumption for the beam itself; this is the first
  place it is relied on for a second framing element, and that has not been
  confirmed against a live host either -- see
  ``rft/revit/guards.py:neighbour_axis_dot_product``.
- ``RebarBarType.BarNominalDiameter`` (issue #20, S7; more load-bearing
  since A42/ticket #27 made it the SOLE diameter source, not one side of a
  cross-check) -- assumed to be a read-only property in internal units
  carrying the catalog/nominal bar diameter. Documentation also lists
  ``BarModelDiameter`` as a plausible alternative; not confirmed against a
  live host which one every downstream mm computation should read. See
  ``rft/revit/bar_types.py``.
- ``RebarHookType.get_Parameter(BuiltInParameter.REBAR_HOOK_ANGLE)
  .AsDouble()`` (issue #25) -- VERIFIED LIVE against Revit 2024
  (``RevitAPI 24.3.40.0``, issue #25/#31 probe): returns the hook's own
  angle in RADIANS, exactly as assumed. Not a new SHAPE UNVERIFIED item
  any more; kept in this list only as a record of what was confirmed and
  when. See ``rft/revit/bar_types.py``.
- ``RebarHookType.get_Parameter(BuiltInParameter.REBAR_HOOK_STYLE)
  .AsInteger()`` (issue #25/#31, A45) -- the live probe VERIFIED that
  `BuiltInParameter.REBAR_HOOK_STYLE` distinguishes Standard (0) from
  Stirrup/Tie (1) hook families and that `RebarStyle.StirrupTie` rejects a
  Standard-family hook with an opaque `InternalException` regardless of
  angle. What the probe did NOT independently confirm is this exact
  accessor call (`get_Parameter(...).AsInteger()`) -- the 0/1 meaning was
  read from the Revit UI/API browser, not by re-probing this specific
  method. Still SHAPE UNVERIFIED on that narrower point. See
  ``rft/revit/bar_types.py``.
- ``pyrevit.forms.SelectFromList.show(items, multiselect=False,
  name_attr=..., title=..., button_name=...)`` (issue #20, S7) -- the
  explicit dropdown/list picker used to select bar and hook types. This is
  NOT faked here at all (``pyrevit`` itself is not importable in this
  environment) -- the three pushbuttons' selection helpers are therefore
  UNEXECUTED, not merely shape-unverified. See each pushbutton's own
  module docstring and docs/verification/s7-grades.md.
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


class FakeUV(object):
    """Stand-in for ``Autodesk.Revit.DB.UV``, the 2D parameter passed to
    ``Face.ComputeNormal`` (confirmed live, issue #23/#30). Only ``U``/``V``
    are exposed; ``rft.revit.host`` never reads them back, it only
    round-trips the object to a fake ``Face.ComputeNormal``."""

    def __init__(self, u=0.0, v=0.0):
        self.U, self.V = u, v


class FakeReference(object):
    """Stand-in for ``Autodesk.Revit.DB.Reference`` -- the geometric
    handle ``RebarHostData.GetExposedFaces()`` returns (confirmed live,
    issue #23). Opaque in the real API; this fake carries a ``label`` only
    for test diagnostics, never read by adapter code."""

    def __init__(self, label):
        self.label = label

    def __repr__(self):
        return "FakeReference({!r})".format(self.label)


class FakeFace(object):
    """Stand-in for the ``Face`` object
    ``Element.GetGeometryObjectFromReference(Reference)`` resolves a
    ``Reference`` into (confirmed live, issue #23). Only ``ComputeNormal``
    is exercised; the real object carries far more (area, curve loops,
    etc.) that this project has no use for."""

    def __init__(self, normal):
        self._normal = normal

    def ComputeNormal(self, _uv):
        return self._normal


class FakeRebarCoverType(object):
    """Stand-in for ``Autodesk.Revit.DB.Structure.RebarCoverType``, the
    object ``RebarHostData.GetCoverType(Reference)`` returns DIRECTLY
    (confirmed live, issue #23/#30 -- NOT an ``ElementId`` needing a
    ``doc.GetElement`` round trip, which was this project's earlier,
    now-corrected assumption). ``CoverDistance`` is confirmed live;
    ``Id``/``Name`` are the standard ``Element`` members, not independently
    probed but not a new assumption either. The live model carried two
    DIFFERENT ``RebarCoverType`` elements sharing the identical ``Name``
    (``"Interior (framing, columns)"``, 38.1 mm and 40 mm) -- callers must
    compare by ``Id``, never ``Name``; this fake supports constructing two
    such distinct-id, same-name instances for exactly that test.
    """

    _next_id = [1]

    def __init__(self, cover_distance_internal, name=None, id_value=None):
        self.CoverDistance = cover_distance_internal
        self.Name = name
        if id_value is None:
            id_value = FakeRebarCoverType._next_id[0]
            FakeRebarCoverType._next_id[0] += 1
        self.Id = FakeElementId(id_value)


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


class FakeRebarHookAngleParameter(object):
    """SHAPE UNVERIFIED -- stand-in for the ``Parameter`` object
    ``RebarHookType.get_Parameter(BuiltInParameter.REBAR_HOOK_ANGLE)`` is
    assumed to return (issue #25). Real return type/member name not
    confirmed; this only carries whatever angle a test assigns, in
    radians, matching ``AsDouble()``'s assumed unit."""

    def __init__(self, angle_deg):
        self._angle_deg = angle_deg

    def AsDouble(self):
        return math.radians(self._angle_deg)


class FakeRebarHookStyleParameter(object):
    """SHAPE UNVERIFIED -- stand-in for the ``Parameter`` object
    ``RebarHookType.get_Parameter(BuiltInParameter.REBAR_HOOK_STYLE)`` is
    assumed to return (issue #25/#31, A45). The 0/1 MEANING (0 = Standard,
    1 = Stirrup/Tie) is VERIFIED LIVE; this specific accessor
    (``AsInteger()``) is not independently re-confirmed. Carries whatever
    style int a test assigns."""

    def __init__(self, style):
        self._style = style

    def AsInteger(self):
        return self._style


class FakeRebarHookType(object):
    """SHAPE UNVERIFIED (narrowed by issue #25/#31's live probe -- see
    module header) -- stand-in for `Autodesk.Revit.DB.Structure.
    RebarHookType`. Real hook angle/style live on the Revit-side object;
    this fake only carries whatever a test assigns for assertion purposes.

    ``angle_deg=None`` simulates a hook type whose angle CANNOT be read
    back at all (``get_Parameter`` returns None for
    ``REBAR_HOOK_ANGLE``) -- issue #25's "unreadable angle" case, distinct
    from an angle that reads back and fails the 135-degree check.

    ``style=None`` (the default) simulates a hook type whose
    ``REBAR_HOOK_STYLE`` CANNOT be read back at all -- issue #25/#31's
    "unreadable style" case, which must REFUSE rather than proceed (see
    ``rft.core.grades.unreadable_hook_style_message``). Pass ``style=1``
    (``HOOK_STYLE_STIRRUP_TIE``) or ``style=0`` (``HOOK_STYLE_STANDARD``)
    to simulate a readable family.
    """

    def __init__(self, angle_deg=None, name=None, style=None):
        self.angle_deg = angle_deg
        self.Name = name
        self.style = style

    def get_Parameter(self, built_in_parameter):
        if built_in_parameter is FakeBuiltInParameter.REBAR_HOOK_STYLE:
            if self.style is None:
                return None
            return FakeRebarHookStyleParameter(self.style)
        if self.angle_deg is None:
            return None
        return FakeRebarHookAngleParameter(self.angle_deg)


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
    """SHAPE UNVERIFIED -- ``BarNominalDiameter`` (issue #20, S7). See
    tests/fake_revit_api.py header."""

    def __init__(self, bar_nominal_diameter=None, name=None):
        self.BarNominalDiameter = bar_nominal_diameter
        self.Name = name


class FakeBuiltInParameter(object):
    """SHAPE UNVERIFIED -- ``REBAR_HOOK_ANGLE`` (issue #25) is verified
    live to return radians; ``REBAR_HOOK_STYLE`` (issue #25/#31, A45) is
    verified live for its 0/1 meaning but not this exact accessor. See
    tests/fake_revit_api.py header."""

    REBAR_HOOK_ANGLE = object()
    REBAR_HOOK_STYLE = object()


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
    db.UV = FakeUV
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
    db.BuiltInParameter = FakeBuiltInParameter
    db.Structure = structure

    structure.RebarHostData = FakeRebarHostData
    structure.RebarStyle = FakeRebarStyle
    structure.RebarHookOrientation = FakeRebarHookOrientation
    structure.Rebar = FakeRebar
    structure.RebarBarType = FakeRebarBarType
    structure.RebarHookType = FakeRebarHookType

    revit_pkg.DB = db
    autodesk_pkg.Revit = revit_pkg

    sys.modules["Autodesk"] = autodesk_pkg
    sys.modules["Autodesk.Revit"] = revit_pkg
    sys.modules["Autodesk.Revit.DB"] = db
    sys.modules["Autodesk.Revit.DB.Structure"] = structure
