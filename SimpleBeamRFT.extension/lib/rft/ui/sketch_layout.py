# -*- coding: utf-8 -*-
"""Where a sketch label actually gets drawn, in PIXELS (issue #62).

Separate from ``rft.ui.sketch``, which works in millimetres and knows
what a label SAYS, because this module answers a different question: given
that the label wants to sit at this pixel and is this many pixels wide,
where does it go so that it is neither clipped by the canvas edge nor
drawn on top of another label?

It lives here, and not in ``script.py``'s renderer, for the reason
everything else in this project has moved out of ``script.py``: that file
imports ``pyrevit`` and cannot be imported under CPython, so nothing in
it can be tested. Label placement is fiddly, ordering-dependent logic --
exactly the kind that needs tests, and exactly the kind that looks fine
in code review and then draws one sentence across another on a live host.

WHAT THIS DOES NOT DO. It never changes what a label says and never
touches a dimension. Every number was computed by ``rft.core`` and
formatted by ``rft.ui.sketch`` before it reaches this module (A48). This
is presentation only: two numbers in, two numbers out.

WHY THE TEXT SIZE IS ESTIMATED. Measuring a WPF ``TextBlock`` requires a
live WPF, which is the thing that cannot be tested. A per-character width
estimate is good enough for the job -- the consequence of being slightly
wrong is a label a few pixels from where it could ideally sit, not a
clipped or overlapping one, because both guarantees are enforced against
whatever size is passed in.

Python 2/3 compatible: IronPython 2.7 is the runtime that loads this in
production.
"""

from collections import namedtuple

# One label's desired placement and its measured/estimated extent.
# ``x``/``y`` are the TOP-LEFT corner in canvas pixels.
LabelBox = namedtuple("LabelBox", "x y width height")

# Average glyph width as a fraction of the font's point size, for the
# 11 px sans-serif the sketch captions use. Deliberately generous: over-
# estimating a label's width pulls it further inside the canvas, which is
# harmless, while under-estimating lets its tail clip, which is the defect
# this module exists to prevent.
CHAR_WIDTH_RATIO = 0.62

# Vertical gap left between two labels that would otherwise overlap.
LINE_GAP_PX = 2.0


def estimate_text_size_px(text, font_size_px=11.0):
    """A label's width and height in pixels, estimated from its length.

    See the module docstring for why this is estimated rather than
    measured. Returns (0, 0) for empty text so an absent label consumes
    no space and cannot displace a real one.
    """
    if not text:
        return 0.0, 0.0
    return (len(text) * font_size_px * CHAR_WIDTH_RATIO, font_size_px)


def clamp_into_canvas(box, canvas_width_px, canvas_height_px):
    """Move one label the shortest distance needed to sit fully inside the
    canvas.

    The defect this fixes: the scale fit bounded each label by its ANCHOR
    POINT, so a label anchored near the right edge had its tail cut off
    mid-word -- "A7 clearanc" on the live run. Clamping after the
    transform is the guarantee, rather than trying to predict the extent
    before choosing a scale, which is circular (the scale depends on the
    bounds, the bounds on the text size, the text size on nothing that
    changes -- but the POSITION depends on the scale).

    A label wider than the whole canvas is pinned to the left edge: some
    of it will be lost, and losing the tail is better than losing the
    beginning, which is the part that says what the number means.
    """
    x = box.x
    y = box.y
    if box.width < canvas_width_px:
        x = min(max(x, 0.0), canvas_width_px - box.width)
    else:
        x = 0.0
    if box.height < canvas_height_px:
        y = min(max(y, 0.0), canvas_height_px - box.height)
    else:
        y = 0.0
    return LabelBox(x, y, box.width, box.height)


def _overlaps(a, b):
    return (a.x < b.x + b.width and b.x < a.x + a.width
            and a.y < b.y + b.height and b.y < a.y + a.height)


def place_labels(boxes, canvas_width_px, canvas_height_px):
    """Final positions for every label: inside the canvas, and not on top
    of one another.

    Boxes are honoured in the order given, so the caller controls
    priority: whatever matters most keeps the position it asked for, and
    later labels move out of its way. The sketch passes its dimension
    labels before its explanatory ones for that reason.

    A colliding label is pushed DOWN a line at a time, then UP if it runs
    out of room below, and left where it is if neither direction can fit
    it -- a drawing with more labels than space should degrade to
    overlapping text rather than to no text at all, since the numbers are
    the point.

    Returns a list of ``LabelBox`` in the same order as the input.
    """
    placed = []
    for box in boxes:
        candidate = clamp_into_canvas(box, canvas_width_px, canvas_height_px)
        if candidate.width <= 0.0 or candidate.height <= 0.0:
            placed.append(candidate)
            continue
        step = candidate.height + LINE_GAP_PX
        resolved = candidate
        for direction in (1.0, -1.0):
            resolved = candidate
            attempts = 0
            # Bounded by how many lines fit in the canvas, so a crowded
            # drawing cannot spin here.
            limit = int(canvas_height_px / step) + 2
            while any(_overlaps(resolved, other) for other in placed):
                attempts += 1
                if attempts > limit:
                    break
                moved = LabelBox(resolved.x, resolved.y + direction * step,
                                 resolved.width, resolved.height)
                clamped = clamp_into_canvas(
                    moved, canvas_width_px, canvas_height_px)
                # Clamping undid the move: this direction is exhausted.
                if abs(clamped.y - resolved.y) < 0.01:
                    break
                resolved = clamped
            if not any(_overlaps(resolved, other) for other in placed):
                break
        placed.append(resolved)
    return placed
