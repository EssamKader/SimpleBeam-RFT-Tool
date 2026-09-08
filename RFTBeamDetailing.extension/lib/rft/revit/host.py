"""Host validation and per-face cover read-back.

Rev 2 section 10: "Host validation order: RebarHostData.GetRebarHostData(beam)
non-null, then IsValidHost(), then explicitly read back per-face
RebarCoverType -- an undefined face cover silently falls back to a document
default and could masquerade as this spec's Cover input."

UNVERIFIED AGAINST A LIVE HOST (docs/research/revit-api-strategy.md section 4
lists this whole area as resting on documentation only): the exact
``RebarHostData`` method used to enumerate faces and read back each face's
``RebarCoverType`` is not nailed down by the research phase. This module
uses ``RebarHostData.GetFaces(RebarFaceType)`` / ``GetCoverType(Face)``,
which is the best-documented candidate, but the enum name/values
(``RebarFaceType`` vs. a differently-named host-face enum) and whether an
undefined cover comes back as ``None`` vs. ``ElementId.InvalidElementId``
have not been confirmed against a live host. See the mock-object
verification write-up (docs/verification/s1-tracer-bullet.md) for how this
is exercised without one.

STRONGER CAVEAT added during the issue #14 review fix pass: published
Revit API reference pages for ``RebarHostData`` (revitapidocs.com, several
versions) describe ``GetExposedFaces() -> IList<Reference>`` and
``GetCoverType(Reference face) -> RebarCoverType`` -- i.e. faces addressed
by geometry ``Reference``, cover returned directly as a ``RebarCoverType``
object -- with no ``GetFaces(RebarFaceType)`` overload and no
``RebarFaceType``-keyed lookup appearing in that documentation at all. That
would mean this module's whole face-enumeration shape (``GetFaces``/an
``ElementId``-valued cover-type lookup via ``doc.GetElement``) may not
match the real API, not just the specific ``RebarFaceType`` member chosen.
This could not be confirmed either way without a live host, so the
existing shape is kept (changing it is a larger redesign than the review's
finding #4 asked for), but this is flagged prominently rather than left as
a quiet aside: **the whole cover-read-back mechanism in this module needs
verification against a real Revit session before this ships**, not only
the ``RebarFaceType.Other`` vs. ``.Bottom`` choice made in script.py.
"""

from Autodesk.Revit.DB import ElementId
from Autodesk.Revit.DB.Structure import RebarHostData


class HostValidationError(Exception):
    """An actionable host-validation failure. Carries the offending
    element's id so the caller can report it (rev 2 section 10)."""

    def __init__(self, message, element_id=None):
        super(HostValidationError, self).__init__(message)
        self.element_id = element_id


def validate_rebar_host(element):
    """§10 host validation order, step 1-2: GetRebarHostData non-null, then
    IsValidHost(). Returns the RebarHostData on success.
    """
    host_data = RebarHostData.GetRebarHostData(element)
    if host_data is None:
        raise HostValidationError(
            "Element {} cannot host rebar: RebarHostData.GetRebarHostData() "
            "returned null. It must be Structural Framing (or another "
            "rebar-capable category) with a concrete material.".format(
                element.Id
            ),
            element_id=element.Id,
        )
    if not host_data.IsValidHost():
        usage = getattr(element, "StructuralUsage", None)
        raise HostValidationError(
            "Element {} is rebar-host-capable but IsValidHost() returned "
            "false. Check its StructuralUsage (currently: {}) -- it must be "
            "set to a valid structural usage for this to host rebar.".format(
                element.Id, usage
            ),
            element_id=element.Id,
        )
    return host_data


def read_face_cover_mm(host_data, face_type, doc, from_internal_units, element_id=None):
    """§10 host validation order, step 3: explicit per-face cover read-back.

    Raises rather than silently accepting a document-default cover, so an
    undefined face cover can never masquerade as the spec's `Cover` input.
    """
    faces = host_data.GetFaces(face_type)
    if not faces:
        raise HostValidationError(
            "No {} face found for cover read-back on element {}.".format(
                face_type, element_id
            ),
            element_id=element_id,
        )
    cover_type_id = host_data.GetCoverType(faces[0])
    if cover_type_id is None or cover_type_id == ElementId.InvalidElementId:
        raise HostValidationError(
            "No explicit RebarCoverType assigned on the {} face of element "
            "{} -- it would silently fall back to the document default "
            "(rev 2 section 10). Assign an explicit cover before "
            "detailing.".format(face_type, element_id),
            element_id=element_id,
        )
    cover_type = doc.GetElement(cover_type_id)
    return from_internal_units(cover_type.CoverDistance)


def read_support_cover_mm(support_element, face_type, doc, from_internal_units):
    """The supporting element's OWN cover (rev 2 section 2.4, A8) -- used in
    the anchorage formulas, distinct from the beam's own face cover.
    """
    host_data = RebarHostData.GetRebarHostData(support_element)
    if host_data is None:
        raise HostValidationError(
            "Support element {} has no RebarHostData; cannot read its own "
            "cover (rev 2 section 2.4).".format(support_element.Id),
            element_id=support_element.Id,
        )
    return read_face_cover_mm(
        host_data, face_type, doc, from_internal_units, element_id=support_element.Id
    )
