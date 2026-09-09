# -*- coding: utf-8 -*-
"""U2 (issue #46) -- the single "Detail Beam" shell: one WPFWindow, five
tabs, one beam-pick flow, one Transaction. The eventual replacement for
"Place Main Bars", "Place Stirrups" and "Place Crack Bars" (A46, A47).

NOTHING IS DELETED BY THIS TICKET. This button is ADDED ALONGSIDE those
three, which stay until the single window has been verified on a live host
-- deletion is #55 (U11), on the project owner's instruction. The ribbon
carries both meanwhile, deliberately: those three are the only VERIFIED
tool (v0.1.0 placed real reinforcement with them on a 0 and a 45 degree
beam), so while the Place button below is still a stub the tool as a whole
is never broken. They do not conflict at runtime -- separate pushbutton
folders, loaded independently by pyRevit, sharing lib/rft read-only.

Keeping them also buys a check that deleting early would have thrown away:
detail the same beam both ways and compare, which is a direct test that this
rework changed the INTERFACE and not the DETAILING. That comparison is an
acceptance criterion on #55.

SCOPE (this ticket only): the window, the tab set, the beam-pick control and
the transaction boundary. Tab CONTENTS -- bar-type pickers, spacing inputs,
the live sketch, the Review-tab derivation and report -- are #47 (U3), #48
(U4) and #50 (U6). The Place button on the Review tab is a LOUD stub: it
opens the one Transaction A46 requires, calls into a placement function that
is not implemented yet, and lets that failure roll the transaction back and
report itself -- naming the tickets that will fill it in. A button that
looks finished and places nothing would be worse than one that says so.

A35 -- the dialog opens FIRST, then the beam is picked: this script shows
the window before anything Revit-specific happens, and every geometry/
support field on "Beam & Materials" is disabled until a beam is picked.
Re-picking repopulates them and re-runs support detection from scratch.

Ordering preserved from today's pushbuttons, load-bearing per this ticket's
brief: continuous-run refusal (A41) -> support detection -> no-support-at-
both-ends refusal -> cover reads -- all of it BEFORE any placement work, and
all of it running again on every re-pick.
"""

from pyrevit import forms, revit, script

from rft.revit.geometry import (
    beam_axis_direction,
    beam_endpoints,
    beam_section_axes,
    beam_section_dimensions_mm,
    find_supporting_element,
    support_width_along_axis_mm,
)
from rft.revit.guards import continuous_run_guard
from rft.revit.host import (
    HostValidationError,
    read_beam_face_covers_mm,
    read_support_side_cover_mm,
    validate_rebar_host,
)
from rft.revit.placement import run_in_transaction
from rft.revit.units import internal_to_mm, mm_to_internal

output = script.get_output()
doc = revit.doc


def _end_support(document, point, axis, beam_id):
    """Detect the support at one beam end (rev 2 section 2.4, A9). A free/
    cantilever end returns (None, None) -- the unsupported path (section
    2.5). Identical helper to every pre-#46 pushbutton's own copy.
    """
    support = find_supporting_element(document, point, mm_to_internal, exclude_element_id=beam_id)
    if support is None:
        return None, None
    width_mm = support_width_along_axis_mm(support, axis, internal_to_mm)
    return support, width_mm


def _format_cover_mm(value_mm):
    """Never format ``None`` numerically -- the exact rc5 crash this
    project already hit once (``"{:.1f}".format(None)``). ``None`` here
    means "no exposed face to read", which is the normal case at a
    SUPPORTED end (rev 2 section 10 / issue #30) -- not a missing value.
    """
    if value_mm is None:
        return "n/a (supported)"
    return "{:.1f} mm".format(value_mm)


def _format_support(is_supported, width_mm, cover_mm):
    if not is_supported:
        return "none detected (free/cantilever end -- rev 2 section 2.5, A14)"
    return "detected, width = {:.1f} mm, support cover = {}".format(
        width_mm, _format_cover_mm(cover_mm)
    )


class DetailBeamWindow(forms.WPFWindow):
    """The five-tab shell (issue #46). Only "Beam & Materials" does any
    real work in this ticket; the other four tabs are placeholders."""

    def __init__(self):
        # Bare filename: WPFWindow._determine_xaml resolves it against
        # EXEC_PARAMS.command_path, the folder this script sits in --
        # confirmed by the #42 spike, not re-derived here.
        forms.WPFWindow.__init__(self, "DetailBeamWindow.xaml")

        self.beam = None
        self.host_data = None

        self.pick_btn.Click += self.on_pick_click
        self.place_btn.Click += self.on_place_click

        self._reset_beam_state(message="No beam picked yet.")

    # ------------------------------------------------------------ picking
    def _reset_beam_state(self, message):
        """A35: every geometry/support field is disabled until a beam is
        picked, and a failed/refused pick must leave the window in exactly
        this same disabled state -- never a half-populated one.
        """
        self.beam = None
        self.host_data = None
        self.geometry_panel.IsEnabled = False
        self.beam_status_tb.Text = message
        self.warnings_tb.Text = ""
        self.l_tb.Text = ""
        self.b_tb.Text = ""
        self.h_tb.Text = ""
        self.covers_tb.Text = ""
        self.start_support_tb.Text = ""
        self.end_support_tb.Text = ""

    def on_pick_click(self, sender, args):
        # Re-picking must repopulate everything and re-run support
        # detection from scratch (A35) -- so the state is reset FIRST,
        # regardless of how far the previous pick got.
        self._reset_beam_state(message="No beam picked yet.")

        beam = revit.pick_element(message="Select a beam (structural framing) to detail.")
        if beam is None:
            return

        try:
            host_data = validate_rebar_host(beam)
        except HostValidationError as ex:
            forms.alert(str(ex), title="Host validation failed")
            return

        start_pt, end_pt = beam_endpoints(beam)
        axis = beam_axis_direction(beam)
        u_dir, v_dir = beam_section_axes(beam)
        b_mm, h_mm = beam_section_dimensions_mm(beam, internal_to_mm)
        # Placeholder L for THIS shell only: the physical location-curve
        # endpoint distance. Rev 2's own L (A6) is support-centre-to-
        # support-centre (`rft.revit.geometry.span_length_mm`), which needs
        # both supports resolved -- not always true here, since one end may
        # be unsupported. #47 (Beam & Materials) owns the real pre-fill
        # rule for this field; this value is only for the shell to have
        # something honest to show and re-populate on every pick.
        l_mm = internal_to_mm(start_pt.DistanceTo(end_pt))

        # --- A41, run BEFORE support detection: a collinear neighbouring
        # beam at either end makes this a continuous run, not a single
        # span, and REFUSES outright rather than being merely warned.
        continuous_guards = [
            g for g in (
                continuous_run_guard(doc, beam, start_pt, mm_to_internal, "Start end", exclude_element_id=beam.Id),
                continuous_run_guard(doc, beam, end_pt, mm_to_internal, "End end", exclude_element_id=beam.Id),
            ) if g is not None
        ]
        if continuous_guards:
            forms.alert(
                "\n\n".join(g.message for g in continuous_guards),
                title="Continuous run detected -- refused",
            )
            return

        # --- support detection, per end, any support type (rev 2 section
        # 2.4/A9) -- run AFTER the continuous-run refusal, BEFORE the
        # no-support refusal and the cover reads, exactly as today's
        # pushbuttons order it.
        support_start, support_width_start_mm = _end_support(doc, start_pt, axis, beam.Id)
        support_end, support_width_end_mm = _end_support(doc, end_pt, axis, beam.Id)
        is_supported_start = support_start is not None
        is_supported_end = support_end is not None

        if not is_supported_start and not is_supported_end:
            forms.alert(
                "No support (column, wall or girder) detected at EITHER end "
                "(rev 2 section 2.4/2.5, A9/A12/A14). This tool details a "
                "single-span, simply-supported beam -- a beam with no "
                "support at all is not a span and is refused outright "
                "rather than silently detailed (this project's own "
                "judgement call, not a rev 2 rule).",
                title="No support detected",
            )
            return

        warning_lines = []
        if not is_supported_start:
            warning_lines.append("Start end: no support detected -- free/cantilever end (A14), warned not refused.")
        if not is_supported_end:
            warning_lines.append("End end: no support detected -- free/cantilever end (A14), warned not refused.")

        # --- cover reads, LAST, only after both refusals above have had
        # their chance to fire (issue #30/#46 ordering): END covers are
        # only requested at whichever end is actually unsupported, since a
        # supported end exposes no end face to read at all.
        try:
            beam_covers = read_beam_face_covers_mm(
                beam, host_data, u_dir, v_dir, axis, internal_to_mm, element_id=beam.Id,
                need_end_start=not is_supported_start, need_end_end=not is_supported_end,
            )
        except HostValidationError as ex:
            forms.alert(str(ex), title="Cover read-back failed")
            return

        support_cover_start_mm = support_cover_end_mm = None
        try:
            if is_supported_start:
                support_start_host_data = validate_rebar_host(support_start)
                support_cover_start_mm = read_support_side_cover_mm(
                    support_start, support_start_host_data, axis, True, internal_to_mm,
                    element_id=support_start.Id,
                )
            if is_supported_end:
                support_end_host_data = validate_rebar_host(support_end)
                support_cover_end_mm = read_support_side_cover_mm(
                    support_end, support_end_host_data, axis, False, internal_to_mm,
                    element_id=support_end.Id,
                )
        except HostValidationError as ex:
            forms.alert(str(ex), title="Cover read-back failed")
            return

        # --- everything above succeeded: populate and enable the fields.
        self.beam = beam
        self.host_data = host_data
        self.beam_status_tb.Text = "Picked beam id {}.".format(beam.Id)
        self.warnings_tb.Text = "\n".join(warning_lines)
        self.l_tb.Text = "{:.1f}".format(l_mm)
        self.b_tb.Text = "{:.1f}".format(b_mm)
        self.h_tb.Text = "{:.1f}".format(h_mm)
        self.covers_tb.Text = (
            "top = {:.1f} mm, bottom = {:.1f} mm, side = {:.1f} mm, "
            "end (start) = {}, end (end) = {}".format(
                beam_covers.top_mm, beam_covers.bottom_mm, beam_covers.side_mm,
                _format_cover_mm(beam_covers.end_start_mm),
                _format_cover_mm(beam_covers.end_end_mm),
            )
        )
        self.start_support_tb.Text = "Start end: " + _format_support(
            is_supported_start, support_width_start_mm, support_cover_start_mm
        )
        self.end_support_tb.Text = "End end: " + _format_support(
            is_supported_end, support_width_end_mm, support_cover_end_mm
        )
        self.geometry_panel.IsEnabled = True

    # ------------------------------------------------------------- place
    def _do_place(self):
        """THE PLACEMENT CALL SITE IS A LOUD STUB, NOT A SILENT NO-OP.

        Main bars, stirrups and crack bars are placed by #47 (Beam &
        Materials -- bar-type/hook selection), #48 (the three
        reinforcement tabs' own inputs) and #50 (Review's derivation rule
        and report), none of which exist yet. Raising here -- inside the
        one Transaction ``run_in_transaction`` already wraps -- is
        deliberate: it proves the rollback path works on a real exception
        before there is anything real to roll back, and it refuses to let
        the engineer believe Place did something it did not.
        """
        raise NotImplementedError(
            "Place is not implemented yet, and nothing has been placed.\n\n"
            "USE THE EXISTING BUTTONS MEANWHILE: \"Place Main Bars\", "
            "\"Place Stirrups\" and \"Place Crack Bars\" are still on the "
            "ribbon and still work -- they are the verified tool (v0.1.0). "
            "They stay until this window has replaced them in practice "
            "(#55).\n\n"
            "This window's placement is built by #47 (Beam & Materials "
            "tab), #48 (Main bars/Stirrups/Crack bars tabs) and #50 "
            "(Review tab's derivation and report). This ticket (#46) built "
            "only the window, the tabs, the beam-pick flow and the "
            "transaction boundary."
        )

    def on_place_click(self, sender, args):
        if self.beam is None:
            forms.alert(
                "Pick a beam on the Beam & Materials tab before pressing "
                "Place (A35).",
                title="No beam picked",
            )
            return
        try:
            run_in_transaction(doc, "RFT Detail Beam", self._do_place)
        except NotImplementedError as ex:
            # The expected path today: the stub refused, the transaction
            # rolled back, nothing was placed.
            message = str(ex)
            self.place_result_tb.Text = message
            forms.alert(message, title="Not implemented yet")
            return
        except Exception as ex:
            # A GENUINE failure, distinguished from the stub deliberately.
            # Titling every exception "Not implemented" would, the moment
            # #47/#48/#50 land, report a real Revit error -- an
            # InternalException from a rejected hook family, say -- as an
            # unfinished feature, and send whoever reads it looking in
            # entirely the wrong place. The transaction has rolled back
            # either way, so the model is unchanged; only the diagnosis
            # differs, and the diagnosis is the whole value of the message.
            message = "Placement FAILED and was rolled back -- {}: {}".format(
                type(ex).__name__, ex
            )
            self.place_result_tb.Text = message
            forms.alert(message, title="Placement failed -- rolled back")
            return
        # Unreachable until #47/#48/#50 land -- self._do_place always
        # raises today, so this line has never executed and must not
        # claim success it cannot back up.
        self.place_result_tb.Text = "Placed successfully."


def main():
    window = DetailBeamWindow()
    window.ShowDialog()


if __name__ == "__main__":
    main()
