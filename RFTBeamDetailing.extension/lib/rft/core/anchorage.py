"""Development length and end-anchorage math for main bars.

Pure Python: no Revit imports, no Revit types. Every value is a plain
number in millimetres, matching the spec 1:1 (rev 2 section 10). Callers
convert to internal units only at the Revit API boundary
(``rft.revit.units``).

Rev 2 section 2.
"""

from collections import namedtuple

DEFAULT_LD_BTM_MULTIPLIER = 55.0  # rev 2 section 2.1 default, assumes St 36/52

MIN_BEND_LEG_MM = 200.0  # rev 2 section 2.3, minimum bend length

AnchorageResult = namedtuple("AnchorageResult", ["a", "b", "ld"])


def development_length(diameter_mm, multiplier):
    """LD = multiplier x diameter (rev 2 section 2.1)."""
    return multiplier * diameter_mm


def bottom_bar_anchorage(support_width_mm, support_cover_mm, ld_btm_mm):
    """Bottom bar anchorage: straight run ``a`` + bent leg ``b`` (§2.2/§2.3).

    ``support_cover_mm`` is the SUPPORTING element's own cover, not the
    beam's (rev 2 section 2.4, A8) -- callers must pass the column's cover,
    never the beam's face cover.

    §2.2:
        a_btm = Support width - Cover
        b_btm = LD_btm - a_btm
    §2.3 governing constraints (A11, straight-leg cap; minimum bend clamp):
        a = min(a_formula, LD - 200)
        b = max(200, LD - a)

    The final ``a``/``b`` here supersede the raw §2.2 ``a_btm``/``b_btm`` --
    the cap on ``a`` and the floor on ``b`` are the values actually built
    into the placed bar's curve list.

    Raises ``ValueError`` if ``ld_btm_mm`` is below the 200 mm minimum bend
    leg: the §2.3 cap ``a = min(a_formula, LD - 200)`` would then go
    negative, reversing the straight segment's direction -- a free-input
    ``LD`` multiplier (script.py) can drive this with a small diameter, and
    a negative/zero ``a`` must never reach the Revit API (issue #14 review
    finding #3).
    """
    if ld_btm_mm < MIN_BEND_LEG_MM:
        raise ValueError(
            "LD_btm = {:.1f} mm is less than the {:.0f} mm minimum bend leg "
            "(rev 2 section 2.3) -- no valid straight-run/bend split exists "
            "for this diameter and LD multiplier. Increase the LD "
            "multiplier or the bar diameter.".format(ld_btm_mm, MIN_BEND_LEG_MM)
        )
    a_formula = support_width_mm - support_cover_mm  # §2.2 a_btm
    a = min(a_formula, ld_btm_mm - MIN_BEND_LEG_MM)  # §2.3 straight-leg cap, A11
    b = max(MIN_BEND_LEG_MM, ld_btm_mm - a)  # §2.3 minimum bend clamp
    return AnchorageResult(a=a, b=b, ld=ld_btm_mm)
