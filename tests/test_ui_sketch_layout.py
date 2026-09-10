# -*- coding: utf-8 -*-
"""#62 -- sketch labels must be readable: never clipped, never overlapping.

`v0.3.0-rc1`'s sketch drew correct numbers illegibly on the owner's first
live run: "A7 clearanc" cut off at the right edge, and two achieved-spacing
labels 0.1 mm apart drawn on top of one another. Both are placement, not
arithmetic -- so both belong in a module that can be tested, rather than
inside the renderer where nothing can execute them.
"""

import pytest

from rft.ui.sketch_layout import (
    LINE_GAP_PX,
    LabelBox,
    clamp_into_canvas,
    estimate_text_size_px,
    place_labels,
)

W, H = 600.0, 240.0


def _boxes(placed):
    return [(round(b.x, 1), round(b.y, 1)) for b in placed]


def _overlap(a, b):
    return (a.x < b.x + b.width and b.x < a.x + a.width
            and a.y < b.y + b.height and b.y < a.y + a.height)


# --- text size -------------------------------------------------------------


def test_a_longer_label_is_estimated_wider():
    short = estimate_text_size_px("172.9 mm")
    long_ = estimate_text_size_px("172.9 mm (PASS), min 50.0 mm")
    assert long_[0] > short[0]
    assert long_[1] == short[1] == 11.0


def test_an_empty_label_takes_no_space():
    """So an absent label cannot displace a real one."""
    assert estimate_text_size_px("") == (0.0, 0.0)
    assert estimate_text_size_px(None) == (0.0, 0.0)


# --- clamping: the clipped-tail defect ------------------------------------


def test_a_label_past_the_right_edge_is_pulled_back_inside():
    """The live defect: "A7 clearance (start): ..." anchored near the
    right-hand support had its tail cut off mid-word.
    """
    width, height = estimate_text_size_px("A7 clearance (start): 41.9 / 14.0 mm (PASS)")
    box = LabelBox(W - 20.0, 100.0, width, height)
    placed = clamp_into_canvas(box, W, H)
    assert placed.x + placed.width <= W
    assert placed.x < box.x           # it really moved


def test_a_label_past_the_left_or_top_edge_is_pushed_in():
    placed = clamp_into_canvas(LabelBox(-40.0, -15.0, 80.0, 11.0), W, H)
    assert placed.x == 0.0
    assert placed.y == 0.0


def test_a_label_already_inside_is_left_exactly_where_it_asked():
    box = LabelBox(120.0, 60.0, 90.0, 11.0)
    assert clamp_into_canvas(box, W, H) == box


def test_a_label_wider_than_the_canvas_keeps_its_beginning():
    """Losing the tail is better than losing the start, which is the part
    that says what the number means.
    """
    placed = clamp_into_canvas(LabelBox(300.0, 50.0, W + 200.0, 11.0), W, H)
    assert placed.x == 0.0


# --- de-collision: the overlapping-spacing defect -------------------------


def test_two_labels_at_the_same_spot_do_not_overlap():
    """The live defect: 172.9 mm and 172.8 mm, two layers 0.1 mm apart,
    drawn on top of each other.
    """
    size = estimate_text_size_px("172.9 mm (PASS), min 50.0 mm")
    a = LabelBox(100.0, 100.0, size[0], size[1])
    b = LabelBox(100.0, 100.3, size[0], size[1])
    placed = place_labels([a, b], W, H)
    assert not _overlap(placed[0], placed[1])
    # The first keeps the position it asked for; the second yields.
    assert placed[0].y == pytest.approx(100.0)
    # It is pushed down from ITS OWN request, not from the first label's,
    # so assert the invariant that matters -- clear of the label above by
    # at least the gap -- rather than an exact sum, which would encode a
    # mental model of the algorithm instead of a requirement of it.
    assert placed[1].y >= placed[0].y + placed[0].height
    assert placed[1].y - (placed[0].y + placed[0].height) <= size[1] + LINE_GAP_PX


def test_the_first_label_wins_so_the_caller_controls_priority():
    size = (120.0, 11.0)
    boxes = [LabelBox(50.0, 80.0, *size) for _ in range(3)]
    placed = place_labels(boxes, W, H)
    assert placed[0].y == pytest.approx(80.0)
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            assert not _overlap(placed[i], placed[j])


def test_labels_that_cannot_fit_downward_move_upward_instead():
    """A label near the bottom edge has nowhere below to go."""
    size = (100.0, 11.0)
    anchored = LabelBox(40.0, H - 11.0, *size)
    second = LabelBox(40.0, H - 11.0, *size)
    placed = place_labels([anchored, second], W, H)
    assert not _overlap(placed[0], placed[1])
    assert placed[1].y < placed[0].y
    assert placed[1].y >= 0.0


def test_every_placed_label_is_inside_the_canvas():
    boxes = [
        LabelBox(-30.0, -10.0, 140.0, 11.0),
        LabelBox(W - 10.0, 20.0, 160.0, 11.0),
        LabelBox(300.0, H + 40.0, 90.0, 11.0),
        LabelBox(300.0, H + 40.0, 90.0, 11.0),
    ]
    for placed in place_labels(boxes, W, H):
        assert 0.0 <= placed.x
        assert placed.x + placed.width <= W + 0.01
        assert 0.0 <= placed.y
        assert placed.y + placed.height <= H + 0.01


def test_a_crowded_canvas_still_returns_every_label():
    """More labels than space must degrade to overlapping text, never to
    missing text: the numbers are the point of the drawing.
    """
    boxes = [LabelBox(10.0, 10.0, 200.0, 11.0) for _ in range(80)]
    placed = place_labels(boxes, 240.0, 60.0)
    assert len(placed) == 80


def test_placement_is_deterministic():
    boxes = [
        LabelBox(100.0, 50.0, 120.0, 11.0),
        LabelBox(105.0, 52.0, 120.0, 11.0),
        LabelBox(110.0, 54.0, 120.0, 11.0),
    ]
    assert _boxes(place_labels(boxes, W, H)) == _boxes(place_labels(boxes, W, H))


def test_an_empty_list_places_nothing():
    assert place_labels([], W, H) == []
