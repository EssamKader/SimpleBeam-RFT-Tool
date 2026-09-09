"""Development length and end-anchorage math for main bars.

Pure Python: no Revit imports, no Revit types. Every value is a plain
number in millimetres, matching the spec 1:1 (rev 2 section 10). Callers
convert to internal units only at the Revit API boundary
(``rft.revit.units``).

Rev 2 section 2.
"""

from collections import namedtuple

DEFAULT_LD_BTM_MULTIPLIER = 55.0  # rev 2 section 2.1 default, assumes St 36/52
DEFAULT_LD_TOP_MULTIPLIER = 60.0  # rev 2 section 2.1 default, assumes St 36/52

MIN_BEND_LEG_MM = 200.0  # rev 2 section 2.3, minimum bend length

AnchorageResult = namedtuple("AnchorageResult", ["a", "b", "ld"])


def development_length(diameter_mm, multiplier):
    """LD = multiplier x diameter (rev 2 section 2.1)."""
    return multiplier * diameter_mm


def _capped_anchorage(a_formula_mm, ld_mm):
    """§2.3 governing constraints, shared by both the top and bottom bar
    formulas (A11 straight-leg cap; minimum bend clamp):

        a = min(a_formula, LD - 200)
        b = max(200, LD - a)

    Raises ``ValueError`` if ``ld_mm`` is below the 200 mm minimum bend
    leg: the cap would then go negative, reversing the straight segment's
    direction -- a free-input ``LD`` multiplier (script.py) can drive this
    with a small diameter, and a negative/zero ``a`` must never reach the
    Revit API (issue #14 review finding #3).
    """
    if ld_mm < MIN_BEND_LEG_MM:
        raise ValueError(
            "LD = {:.1f} mm is less than the {:.0f} mm minimum bend leg "
            "(rev 2 section 2.3) -- no valid straight-run/bend split exists "
            "for this diameter and LD multiplier. Increase the LD "
            "multiplier or the bar diameter.".format(ld_mm, MIN_BEND_LEG_MM)
        )
    a = min(a_formula_mm, ld_mm - MIN_BEND_LEG_MM)
    b = max(MIN_BEND_LEG_MM, ld_mm - a)
    return AnchorageResult(a=a, b=b, ld=ld_mm)


def bottom_bar_anchorage(support_width_mm, support_cover_mm, ld_btm_mm):
    """Bottom bar anchorage: straight run ``a`` + bent leg ``b`` (§2.2/§2.3).

    ``support_cover_mm`` is the SUPPORTING element's own cover, not the
    beam's (rev 2 section 2.4, A8) -- callers must pass the support's own
    cover, never the beam's face cover.

    §2.2:
        a_btm = Support width - Cover
        b_btm = LD_btm - a_btm
    §2.3 governing constraints applied by ``_capped_anchorage`` (A11,
    straight-leg cap; minimum bend clamp):
        a = min(a_formula, LD - 200)
        b = max(200, LD - a)

    The final ``a``/``b`` here supersede the raw §2.2 ``a_btm``/``b_btm`` --
    the cap on ``a`` and the floor on ``b`` are the values actually built
    into the placed bar's curve list.

    Raises ``ValueError`` -- see ``_capped_anchorage``.
    """
    a_formula = support_width_mm - support_cover_mm  # §2.2 a_btm
    return _capped_anchorage(a_formula, ld_btm_mm)


def top_bar_anchorage(support_width_mm, support_cover_mm, bottom_bar_diameter_mm, ld_top_mm):
    """Top bar anchorage: straight run ``a_t`` + bent leg ``b_t``, bending
    DOWNWARD (§2.1, §2.2).

        a_t = Support width - Cover - O_BTM
        b_t = LD_top - a_t

    ``support_cover_mm`` is the SUPPORTING element's own cover, not the
    beam's (rev 2 section 2.4, A8) -- same rule as ``bottom_bar_anchorage``.

    ``bottom_bar_diameter_mm`` (O_BTM) IS DELIBERATE, NOT A TYPO: the term
    subtracted here is the BOTTOM bar's own diameter, never the top bar's
    (rev 2 section 2.2, A7). It sizes clearance against the bottom bar's
    own bend at the same joint, not against the top bar's own geometry --
    "fixing" this to the top bar's diameter silently reintroduces the
    clash §2.1 exists to avoid. See ``top_bottom_clearance_mm`` for the
    resulting centreline-separation check this term is meant to guarantee.

    §2.3's cap/clamp discipline is shared with the bottom bar via
    ``_capped_anchorage`` -- not duplicated here.

    Raises ``ValueError`` -- see ``_capped_anchorage``.
    """
    a_formula = support_width_mm - support_cover_mm - bottom_bar_diameter_mm  # §2.1/§2.2
    return _capped_anchorage(a_formula, ld_top_mm)


ClearanceResult = namedtuple("ClearanceResult", ["achieved_mm", "required_mm", "ok"])


def top_bottom_clearance_mm(top_bar_diameter_mm, bottom_bar_diameter_mm):
    """The centreline separation between the top and bottom bars' straight
    legs, and whether it clears the required minimum (rev 2 section 2.2,
    A7).

    By construction (§2.1/§2.2 formulas), ``a_btm - a_t = O_BTM`` always --
    this holds independent of support width or cover, since both formulas
    subtract the same ``Support width - Cover`` term before ``a_t``
    additionally subtracts O_BTM. The required separation is
    ``(O_TOP + O_BTM) / 2``.

    VERIFIED DERIVATION (per this ticket's instructions): the achieved
    separation is fixed at O_BTM regardless of O_TOP, so the clearance
    holds -- ``achieved >= required`` -- only when
    ``O_BTM >= (O_TOP + O_BTM) / 2``, i.e. only when ``O_TOP <= O_BTM``.
    For O_TOP=12 / O_BTM=16: achieved=16 against required=14, 2 mm of
    slack. For O_TOP=25 / O_BTM=16: achieved=16 against required=20.5 --
    a clash. Since both diameters are user inputs, this rule does not
    protect every input combination -- see this ticket's report; rev 2
    does not say what to do when it fails, and this function does not
    decide that -- it only reports achieved vs. required (see
    ``top_bottom_clearance_warning``).

    This checks the FORMULA-LEVEL invariant (the difference the §2.1/§2.2
    formulas guarantee before §2.3's cap/clamp is applied), not the actual
    placed ``a`` values -- if the §2.3 cap fires asymmetrically between the
    top and bottom bar (e.g. different LD multipliers or a very short
    support), the ACTUAL as-built separation could differ from this. That
    is a further, un-asked-for gap this ticket does not close; flagged in
    the report.
    """
    achieved_mm = bottom_bar_diameter_mm
    required_mm = 0.5 * (top_bar_diameter_mm + bottom_bar_diameter_mm)
    return ClearanceResult(achieved_mm=achieved_mm, required_mm=required_mm, ok=achieved_mm >= required_mm)


def top_bottom_clearance_warning(top_bar_diameter_mm, bottom_bar_diameter_mm):
    """Non-blocking warning naming achieved vs. required centreline
    separation when ``top_bottom_clearance_mm`` fails (rev 2 section 2.2,
    A7). Returns None if the clearance holds.

    Rev 2 does not say what to do on failure -- this is a SPEC GAP (see
    this ticket's report): warn, refuse, or auto-adjust is not decided
    here. A warning is chosen because it surfaces information rather than
    deciding, matching how R1 and R3 were resolved -- but this specific
    choice is this ticket's own judgement call, not a rev 2 rule, and a
    decision ticket is needed to confirm or override it.
    """
    result = top_bottom_clearance_mm(top_bar_diameter_mm, bottom_bar_diameter_mm)
    if result.ok:
        return None
    return (
        "Top/bottom bar centreline clearance NOT achieved (rev 2 section "
        "2.2, A7): achieved separation = O_BTM = {:.1f} mm, required = "
        "(O_TOP + O_BTM)/2 = {:.1f} mm, for O_TOP = {:.1f} mm, "
        "O_BTM = {:.1f} mm. Rev 2 does not state what to do when O_TOP > "
        "O_BTM -- this is a non-blocking warning, not a refusal; a "
        "decision ticket is needed (spec gap, see this ticket's "
        "report).".format(
            result.achieved_mm, result.required_mm, top_bar_diameter_mm, bottom_bar_diameter_mm
        )
    )


def placed_clearance_mm(a_btm_mm, a_top_mm, top_bar_diameter_mm, bottom_bar_diameter_mm):
    """The A7 clearance measured on the ``a`` values ACTUALLY BUILT into the
    bars, rather than on the §2.1/§2.2 formulas before §2.3's cap.

    ``top_bottom_clearance_mm`` checks the formula-level invariant
    ``a_btm - a_t = O_BTM``. That invariant does NOT survive §2.3's
    ``a = min(a_formula, LD - 200)`` when the cap fires on one bar and not
    the other, which happens whenever a support is wide relative to LD --
    and LD_top and LD_btm are independent multipliers (60 vs 55), so the
    two bars cap at different widths.

    Worked case that the formula-level check passes and this one catches
    (issue #15 review): O_TOP = O_BTM = 16, a 800 mm support with 25 mm
    cover. Support width - Cover = 775. a_btm = min(775, 880-200) = 680;
    a_t = min(775-16, 960-200) = 759. The bottom bar's straight leg ends
    680 mm in, the top bar's 759 mm in -- the top leg runs 79 mm PAST the
    bottom one, so the achieved separation is -79 mm where the formula
    check still reports a comfortable +16 mm.

    A negative achieved value means the two bends have crossed, not merely
    that they are close.
    """
    achieved_mm = a_btm_mm - a_top_mm
    required_mm = 0.5 * (top_bar_diameter_mm + bottom_bar_diameter_mm)
    return ClearanceResult(achieved_mm=achieved_mm, required_mm=required_mm, ok=achieved_mm >= required_mm)


def placed_clearance_warning(a_btm_mm, a_top_mm, top_bar_diameter_mm, bottom_bar_diameter_mm,
                             end_label=""):
    """Non-blocking warning when ``placed_clearance_mm`` fails at one end.
    Returns None when it holds.

    Same spec gap as ``top_bottom_clearance_warning``: rev 2 does not say
    what to do when the clearance fails, so this reports rather than
    decides.
    """
    result = placed_clearance_mm(a_btm_mm, a_top_mm, top_bar_diameter_mm, bottom_bar_diameter_mm)
    if result.ok:
        return None
    crossed = " The two bends have CROSSED, not merely closed up." if result.achieved_mm < 0 else ""
    return (
        "{}As-built top/bottom clearance NOT achieved (rev 2 section 2.2, "
        "A7, measured on the placed `a` values after section 2.3's cap): "
        "a_btm = {:.1f} mm, a_t = {:.1f} mm, achieved separation = "
        "{:.1f} mm, required = (O_TOP + O_BTM)/2 = {:.1f} mm.{} Section "
        "2.3's cap fired asymmetrically between the two bars, so the "
        "formula-level A7 invariant does not hold as built. Rev 2 does not "
        "state what to do here -- non-blocking warning, decision ticket "
        "needed.".format(
            "{}: ".format(end_label) if end_label else "",
            a_btm_mm, a_top_mm, result.achieved_mm, result.required_mm, crossed,
        )
    )


def unsupported_end_straight_run_mm(distance_to_beam_end_mm, beam_end_cover_mm):
    """§2.5, A12, R3 (resolved): at an unsupported end the bar runs
    straight to ``beam end - cover``.

    ``beam_end_cover_mm`` is the BEAM's OWN end-face cover -- a THIRD cover
    value in this ticket, distinct from both the supporting element's own
    cover used in ``top_bar_anchorage``/``bottom_bar_anchorage`` (rev 2
    section 2.4, A8) and the beam's FACE cover used across sections 4, 6
    and 7 (rev 2 section 1, A4). The beam's own END face (as opposed to a
    side/top/bottom face) is only ever exposed at an unsupported/free end
    (issue #30) -- ``rft.revit.host.read_beam_face_covers_mm`` reads it
    conditionally for exactly that reason.

    ``distance_to_beam_end_mm`` is the adapter-computed geometric distance
    (mm) from wherever this bar's straight run begins to the beam's own
    physical end point, BEFORE the cover subtraction -- this function only
    applies the cover so callers do not re-derive the subtraction
    themselves.
    """
    return distance_to_beam_end_mm - beam_end_cover_mm


UnsupportedEndResult = namedtuple("UnsupportedEndResult", ["achieved_length_mm", "ld_mm", "warning"])


def unsupported_end_anchorage(achieved_length_mm, ld_mm, terminates_short_of_end_mm=None):
    """§2.5/A12: no hook at an unsupported end -- the §2.3 mandatory-hook
    rule must NOT fire here. R3 (resolved): warn naming both the required
    ``LD`` and the achieved length whenever the straight run falls short of
    it.

    ``achieved_length_mm`` is the embedment INTO A SUPPORT actually
    achieved at this end, which at an unsupported end is **0** -- there is
    no support to embed into. Do NOT pass the bar end's geometric position
    relative to the beam end (``-cover``): that is where the bar STOPS, not
    a length of anchorage, and reporting it as one puts a negative length
    in front of the engineer (issue #15 review).

    ``terminates_short_of_end_mm`` is that geometric fact, reported
    separately and correctly: the bar runs straight to ``beam end - cover``
    (R3), i.e. it stops this far short of the beam's own end.
    """
    warning = None
    if achieved_length_mm < ld_mm:
        termination = ""
        if terminates_short_of_end_mm is not None:
            termination = (
                " The bar runs straight, with no hook, stopping {:.1f} mm "
                "short of the beam end (beam end - cover, R3).".format(
                    terminates_short_of_end_mm
                )
            )
        warning = (
            "Unsupported beam end (rev 2 section 2.5, A12; residual "
            "question R3, resolved): this end achieves {:.1f} mm of "
            "embedment against LD = {:.1f} mm required.{}".format(
                achieved_length_mm, ld_mm, termination
            )
        )
    return UnsupportedEndResult(achieved_length_mm=achieved_length_mm, ld_mm=ld_mm, warning=warning)


def free_end_configuration_warning():
    """§2.5, A14: a cantilever/free end is out of scope for v1. It takes
    the unsupported-end path (``unsupported_end_anchorage``) but the
    configuration itself must also be flagged as unsupported, independent
    of whether that path's own LD warning fires.
    """
    return (
        "No support detected at this beam end (rev 2 section 2.5, A14): "
        "cantilever and free ends are OUT OF SCOPE for v1. The tool "
        "proceeds with a straight, no-hook anchorage at this end, but this "
        "configuration is not a supported v1 configuration and should be "
        "reviewed."
    )
