"""Host validation and per-face cover read-back.

Rev 2 section 10: "Host validation order: RebarHostData.GetRebarHostData(beam)
non-null, then IsValidHost(), then explicitly read back per-face
RebarCoverType -- an undefined face cover silently falls back to a document
default and could masquerade as this spec's Cover input."

VERIFIED AGAINST A LIVE HOST -- Revit 2024, `RevitAPI 24.3.40.0` (issue #23,
probed live via MCP connector; see issue #30 for the replacement design this
module now implements). Confirmed live:

- ``DB.Structure.RebarFaceType`` DOES NOT EXIST. It is not a real enum; the
  compiler rejects it outright. Every previous cover read in this module
  built on that enum was wrong, not merely unverified.
- The real ``RebarHostData`` surface is::

      IList<Reference> GetExposedFaces()
      RebarCoverType   GetCoverType(Reference face)
      RebarCoverType   GetCommonCoverType()
      Boolean          IsFaceExposed(Reference face)
      Boolean          IsValidHost()

  Cover is keyed by a geometric ``Reference`` to a face, not by any face-role
  enum -- there is no way to ask for "the top cover" by name.
- ``face.ComputeNormal(UV(0.5, 0.5))`` and
  ``Element.GetGeometryObjectFromReference(Reference)`` both work live and
  were how the probe recovered each face's normal.
- A supported beam's ``GetExposedFaces()`` returns FOUR faces (TOP, BOTTOM,
  two SIDEs) -- NOT six. Both end faces are inside their supporting columns
  and so are never exposed. ``cover_end`` therefore has no face to read on a
  supported beam; it is only meaningful at an unsupported/free end (rev 2
  section 2.5, A12, R3), which is the one case where the end face *would* be
  exposed.
- The live model carried TWO DIFFERENT ``RebarCoverType`` elements with the
  IDENTICAL name ``Interior (framing, columns)`` (38.1 mm and 40 mm). Cover
  types must be compared by element id, never by name.

So this module now resolves a face's ROLE (TOP/BOTTOM/SIDE/END) by
classifying its ``ComputeNormal`` against the beam's own local frame
(``rft.revit.geometry.beam_section_axes``' ``u_dir``/``v_dir`` plus the
beam's axis direction), rather than looking it up by a nonexistent enum. An
oblique or unclassifiable face is refused, never guessed.

STILL UNVERIFIED AGAINST A LIVE HOST:
- ``RebarCoverType`` is assumed to expose ``CoverDistance`` (internal units)
  and the standard ``Element`` ``Id``/``Name`` -- ``CoverDistance`` was
  confirmed live (issue #23); ``Id``/``Name`` were not specifically probed
  but are standard ``Element`` members.
- The support's own cover (rev 2 section 2.4, A8) is resolved here by
  classifying the SUPPORT's own exposed faces against the shared beam AXIS
  direction only (not the beam's ``u_dir``/``v_dir`` cross-section frame,
  and not any support-local frame this project derives elsewhere) -- see
  ``read_support_side_cover_mm``'s docstring. This is this ticket's own
  engineering choice for "the support's own frame" (issue #30's brief item
  6), not something rev 2 itself defines or something confirmed live.
"""

from collections import namedtuple

from Autodesk.Revit.DB import UV
from Autodesk.Revit.DB.Structure import RebarHostData

FACE_ROLE_TOP = "TOP"
FACE_ROLE_BOTTOM = "BOTTOM"
FACE_ROLE_SIDE = "SIDE"
FACE_ROLE_END_START = "END (start)"
FACE_ROLE_END_END = "END (end)"

# How closely a face normal must align with a frame direction to be
# classified against it (cos of ~2.5 degrees). Exact for any rectangular
# prismatic beam; real geometry noise (draft faces, chamfers) would fail
# below this and correctly refuse rather than guess.
NORMAL_ALIGNMENT_TOL = 0.999

BeamFaceCovers = namedtuple(
    "BeamFaceCovers", ["top_mm", "bottom_mm", "side_mm", "end_start_mm", "end_end_mm"]
)


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


def face_normal(element, face_reference):
    """Confirmed live (issue #23): ``Element.GetGeometryObjectFromReference``
    resolves the geometric ``Reference`` ``RebarHostData.GetExposedFaces()``
    returns into an actual face, whose ``ComputeNormal`` gives the outward
    unit normal at that point.
    """
    face = element.GetGeometryObjectFromReference(face_reference)
    return face.ComputeNormal(UV(0.5, 0.5)).Normalize()


def classify_face_role(normal, u_dir, v_dir, axis, tol=NORMAL_ALIGNMENT_TOL):
    """Resolve a face's role from its normal against the beam's own local
    frame (issue #30) -- never a world-axis shortcut, which passes on a
    beam running along a project axis and silently fails on a rotated one
    (the same trap issue #18's review found in the bounding-box code).

    Checked in the order TOP/BOTTOM, then END, then SIDE, per the ticket's
    proven design. Returns ``None`` -- refuse, never guess -- when the
    normal is oblique to all three directions within tolerance.
    """
    dot_v = normal.DotProduct(v_dir)
    if abs(dot_v) > tol:
        return FACE_ROLE_TOP if dot_v > 0 else FACE_ROLE_BOTTOM
    dot_axis = normal.DotProduct(axis)
    if abs(dot_axis) > tol:
        return FACE_ROLE_END_END if dot_axis > 0 else FACE_ROLE_END_START
    dot_u = normal.DotProduct(u_dir)
    if abs(dot_u) > tol:
        return FACE_ROLE_SIDE
    return None


def _cover_mm_from_cover_type(cover_type, from_internal_units, face_label, element_id):
    """§10 step 3: an undefined ``RebarCoverType`` must raise, never
    silently fall back to the document default (rev 2 section 10)."""
    if cover_type is None:
        raise HostValidationError(
            "No explicit RebarCoverType assigned on the {} face of element "
            "{} -- it would silently fall back to the document default "
            "(rev 2 section 10). Assign an explicit cover before "
            "detailing.".format(face_label, element_id),
            element_id=element_id,
        )
    return from_internal_units(cover_type.CoverDistance)


def classify_exposed_faces(element, host_data, u_dir, v_dir, axis, element_id=None):
    """All of ``element``'s exposed faces (``GetExposedFaces()``), classified
    by role and paired with their ``RebarCoverType`` (``GetCoverType``).
    Raises on the first face whose normal cannot be classified -- naming the
    offending face's normal and index, never guessing its role.
    """
    buckets = {
        FACE_ROLE_TOP: [],
        FACE_ROLE_BOTTOM: [],
        FACE_ROLE_SIDE: [],
        FACE_ROLE_END_START: [],
        FACE_ROLE_END_END: [],
    }
    faces = host_data.GetExposedFaces()
    for index, reference in enumerate(faces):
        normal = face_normal(element, reference)
        role = classify_face_role(normal, u_dir, v_dir, axis)
        if role is None:
            raise HostValidationError(
                "Exposed face #{} of element {} has a normal ({:.4f}, "
                "{:.4f}, {:.4f}) that is oblique to the beam's TOP/BOTTOM, "
                "END and SIDE directions within tolerance -- refusing to "
                "guess its role rather than silently masquerading as one of "
                "them (rev 2 section 10).".format(
                    index, element_id, normal.X, normal.Y, normal.Z
                ),
                element_id=element_id,
            )
        buckets[role].append((reference, host_data.GetCoverType(reference)))
    return buckets


def read_beam_face_covers_mm(element, host_data, u_dir, v_dir, axis, from_internal_units,
                              element_id=None, need_end_start=False, need_end_end=False):
    """Reads all cover values the tool needs off ``element``'s own exposed
    faces (issue #30's replacement for the nonexistent ``RebarFaceType``).

    TOP and BOTTOM must each resolve to exactly one face. SIDE must resolve
    to exactly two faces (both sides of the section) whose cover types are
    asserted EQUAL by element id -- never by name, since the live model
    carries two distinct cover types sharing the same name -- and a
    mismatch is a refusal, not a silent pick of the first one found.

    END faces are only read when the caller says it needs them
    (``need_end_start``/``need_end_end``): a supported beam has no exposed
    end face at all, so ``cover_end`` must stay conditional on the
    unsupported-end path (rev 2 section 2.5, A12, R3) that actually needs
    it. Requesting an end that has no exposed face is a refusal, never a
    fallback to another face's cover.
    """
    buckets = classify_exposed_faces(element, host_data, u_dir, v_dir, axis, element_id=element_id)

    def _single(role, label):
        faces = buckets[role]
        if not faces:
            raise HostValidationError(
                "No {} face found for cover read-back on element {}.".format(
                    label, element_id
                ),
                element_id=element_id,
            )
        if len(faces) > 1:
            raise HostValidationError(
                "{} faces classified as {} on element {} -- expected exactly "
                "one; refusing to guess which governs.".format(
                    len(faces), label, element_id
                ),
                element_id=element_id,
            )
        _, cover_type = faces[0]
        return _cover_mm_from_cover_type(cover_type, from_internal_units, label, element_id)

    def _side():
        faces = buckets[FACE_ROLE_SIDE]
        if len(faces) != 2:
            raise HostValidationError(
                "Expected exactly 2 SIDE faces on element {}, found {} -- "
                "cannot resolve the side cover.".format(element_id, len(faces)),
                element_id=element_id,
            )
        (_, cover_a), (_, cover_b) = faces
        cover_a_mm = _cover_mm_from_cover_type(cover_a, from_internal_units, "SIDE", element_id)
        cover_b_mm = _cover_mm_from_cover_type(cover_b, from_internal_units, "SIDE", element_id)
        if getattr(cover_a, "Id", None) != getattr(cover_b, "Id", None):
            raise HostValidationError(
                "The two SIDE faces of element {} carry different cover "
                "types ({:.1f} mm vs {:.1f} mm) -- refusing to silently pick "
                "one (rev 2 section 10).".format(element_id, cover_a_mm, cover_b_mm),
                element_id=element_id,
            )
        return cover_a_mm

    def _end(role, label, required):
        faces = buckets[role]
        if not faces:
            if required:
                raise HostValidationError(
                    "No {} face exposed on element {} -- required for the "
                    "unsupported-end path (rev 2 section 2.5, A12, R3).".format(
                        label, element_id
                    ),
                    element_id=element_id,
                )
            return None
        if len(faces) > 1:
            raise HostValidationError(
                "{} faces classified as {} on element {} -- expected at most "
                "one.".format(len(faces), label, element_id),
                element_id=element_id,
            )
        _, cover_type = faces[0]
        return _cover_mm_from_cover_type(cover_type, from_internal_units, label, element_id)

    return BeamFaceCovers(
        top_mm=_single(FACE_ROLE_TOP, FACE_ROLE_TOP),
        bottom_mm=_single(FACE_ROLE_BOTTOM, FACE_ROLE_BOTTOM),
        side_mm=_side(),
        end_start_mm=_end(FACE_ROLE_END_START, FACE_ROLE_END_START, need_end_start),
        end_end_mm=_end(FACE_ROLE_END_END, FACE_ROLE_END_END, need_end_end),
    )


def read_support_side_cover_mm(support, host_data, axis_direction, is_start_support,
                                from_internal_units, element_id=None, tol=NORMAL_ALIGNMENT_TOL):
    """The supporting element's OWN cover (rev 2 section 2.4, A8) -- used in
    the anchorage formulas, distinct from any of the beam's own face covers.

    Resolved against the SUPPORT's own exposed faces, classified by the
    SHARED beam axis direction alone -- NOT the beam's (u_dir, v_dir)
    cross-section frame, which describes the beam's own width/height and
    has no meaning against a column's faces (issue #30's brief item 6: "a
    column's side face is not the beam's side face").

    THE FACE THAT GOVERNS IS THE FAR ONE -- the face the anchored bar's TIP
    APPROACHES, NOT the face it enters through. Section 2.2's `a =
    support_width - cover` measures `a` inward from the face the bar enters
    (the one toward the span, which ``start_support_face_point`` /
    ``end_support_face_point`` return), so the tip lands exactly `cover`
    short of the OPPOSITE face -- and it is that opposite face's own cover
    which decides where the bar may stop. On a support with equal cover all
    round the two readings coincide, which is why picking the wrong one
    would go unnoticed; on an edge column with a larger exterior cover they
    differ, and the exterior value is the correct one.

    So for the START support the governing face has an outward normal along
    **-axis_direction** (pointing away from the span), and for the END
    support along **+axis_direction**. Do not "correct" this to the face
    nearer the beam: the sign is deliberate and
    ``test_read_support_side_cover_mm_start_support_reads_the_far_face``
    pins it with different covers on the two faces so an inversion fails
    loudly.

    This is this ticket's own design choice for "the support's own frame"
    (rev 2 section 2.4 does not itself define one); it has not been
    confirmed against a live host with a non-symmetric support cross-section.
    """
    expected_positive = not is_start_support
    faces = host_data.GetExposedFaces()
    candidates = []
    for reference in faces:
        normal = face_normal(support, reference)
        dot_axis = normal.DotProduct(axis_direction)
        if abs(dot_axis) > tol and (dot_axis > 0) == expected_positive:
            candidates.append(host_data.GetCoverType(reference))
    label = "support far face (the face the anchored bar's tip approaches)"
    if not candidates:
        raise HostValidationError(
            "No exposed face on support {} aligns with the beam axis on the "
            "far side (the face the anchored bar's tip approaches) -- cannot "
            "read the cover that limits the embedment (rev 2 section 2.4, "
            "A8).".format(element_id),
            element_id=element_id,
        )
    if len(candidates) > 1:
        raise HostValidationError(
            "{} exposed faces on support {} align with the beam axis on the "
            "far side (the face the anchored bar's tip approaches) -- "
            "refusing to guess which governs (rev 2 section 2.4, "
            "A8).".format(len(candidates), element_id),
            element_id=element_id,
        )
    return _cover_mm_from_cover_type(candidates[0], from_internal_units, label, element_id)
