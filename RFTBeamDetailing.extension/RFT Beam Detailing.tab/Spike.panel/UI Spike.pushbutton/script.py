# -*- coding: utf-8 -*-
"""THROWAWAY SPIKE for issue #42 -- proves the UI hosting, nothing else.

Nothing in this file ships. It exists to settle, by running rather than by
reading source, the five things the real UI would otherwise be designed
against as assumptions:

1. A ``WPFWindow`` loading a XAML **file** from inside a ``*.pushbutton``
   folder by bare filename.
2. A ``TabControl`` that switches without breaking under pyRevit's injected
   theme resources. This is the one element with NO precedent in pyRevit's
   own 187 shipped XAML files (``docs/research/ui-wpf-hosting.md``), which is
   the main reason this spike exists.
3. A ``Canvas`` drawn from IronPython at a scale computed from numbers.
4. Whether a relative bitmap path resolves -- from code AND declared in
   XAML. A definite "no" is as useful as a yes: it settles image-versus-
   vector permanently.
5. Whether redraw-on-keystroke is smooth enough, answered with a measured
   millisecond figure rather than a feeling.

It also demonstrates A48's binding rule in miniature: **every dimension
drawn comes from an ``rft.core`` function**, never from arithmetic in the
renderer. The one exception is called out inline, and it is exactly the gap
A48 already records as needing a core addition.

Deliberately absent: any real detailing input, validation, persistence,
transaction or placement.
"""

import os
import time

from pyrevit import forms, framework, script

# rft.core is pure and Revit-free, so it imports fine in a UI context --
# itself worth proving, since A48 makes the renderer depend on it.
from rft.core.layout import corner_bar_u_positions_mm, first_layer_offset_mm
from rft.core.stirrups import centreline_leg_dimensions_mm

output = script.get_output()

Shapes = framework.Windows.Shapes
Media = framework.Media
Windows = framework.Windows


def _brush(r, g, b):
    return Media.SolidColorBrush(Media.Color.FromArgb(255, r, g, b))


CONCRETE = _brush(120, 120, 120)
COVER_LINE = _brush(180, 180, 180)
STIRRUP = _brush(0, 110, 200)
BAR = _brush(200, 40, 40)
DIM = _brush(60, 60, 60)


class SpikeWindow(forms.WPFWindow):
    """Tabbed window with a live section sketch."""

    def __init__(self):
        # Bare filename: pyRevit's WPFWindow._determine_xaml joins
        # EXEC_PARAMS.command_path when the path does not exist as given,
        # so this resolves to the XAML beside this script.
        forms.WPFWindow.__init__(self, "SpikeWindow.xaml")

        self._redraws = 0
        self._total_ms = 0.0
        self._worst_ms = 0.0

        for box in (self.b_tb, self.h_tb, self.cover_tb,
                    self.stirrup_tb, self.bar_tb, self.count_tb):
            box.TextChanged += self.on_input_changed

        self.section_canvas.SizeChanged += self.on_input_changed

        self._run_image_probes()
        self._write_notes()
        self.redraw()

    # ---------------------------------------------------------------- inputs
    def _num(self, box, default):
        """Whatever is in the box, or the default. A spike does not validate."""
        try:
            return float(box.Text)
        except (ValueError, TypeError):
            return default

    def _inputs(self):
        return {
            "b": self._num(self.b_tb, 300.0),
            "h": self._num(self.h_tb, 900.0),
            "cover": self._num(self.cover_tb, 25.0),
            "stirrup": self._num(self.stirrup_tb, 10.0),
            "bar": self._num(self.bar_tb, 16.0),
            "count": max(1, int(self._num(self.count_tb, 4.0))),
        }

    # --------------------------------------------------------------- drawing
    def on_input_changed(self, sender, args):
        self.redraw()

    def redraw(self):
        started = time.clock() if hasattr(time, "clock") else time.time()
        try:
            self._draw()
        except Exception as ex:
            # A spike that dies on a half-typed number proves nothing about
            # smoothness, which is one of the things being measured.
            self.status.Text = "draw failed: {}: {}".format(
                type(ex).__name__, ex
            )
            return
        elapsed_ms = ((time.clock() if hasattr(time, "clock") else time.time())
                      - started) * 1000.0

        self._redraws += 1
        self._total_ms += elapsed_ms
        self._worst_ms = max(self._worst_ms, elapsed_ms)
        self.status.Text = (
            "redraws: {}   last: {:.1f} ms   mean: {:.1f} ms   worst: {:.1f} ms"
            "   (this is the #42 smoothness answer)".format(
                self._redraws, elapsed_ms,
                self._total_ms / self._redraws, self._worst_ms
            )
        )

    def _draw(self):
        canvas = self.section_canvas
        canvas.Children.Clear()

        v = self._inputs()
        b_mm, h_mm = v["b"], v["h"]
        if b_mm <= 0 or h_mm <= 0:
            return

        cw = canvas.ActualWidth or 500.0
        ch = canvas.ActualHeight or 400.0
        margin = 60.0
        scale = min((cw - 2 * margin) / b_mm, (ch - 2 * margin) / h_mm)
        if scale <= 0:
            return

        # mm (section-local u,v, centroid origin, v up) -> canvas px (y down)
        def px(u_mm, v_mm):
            return (cw / 2.0 + u_mm * scale, ch / 2.0 - v_mm * scale)

        def rect(w_mm, hh_mm, brush, thickness, dash=None):
            r = Shapes.Rectangle()
            r.Width = w_mm * scale
            r.Height = hh_mm * scale
            r.Stroke = brush
            r.StrokeThickness = thickness
            if dash:
                # DoubleCollection, built by Add: framework exposes no
                # Double type to parameterise a generic List with.
                dashes = Media.DoubleCollection()
                for d in dash:
                    dashes.Add(d)
                r.StrokeDashArray = dashes
            left, top = px(-w_mm / 2.0, hh_mm / 2.0)
            Windows.Controls.Canvas.SetLeft(r, left)
            Windows.Controls.Canvas.SetTop(r, top)
            canvas.Children.Add(r)

        def label(text, u_mm, v_mm, brush=DIM, size=11):
            t = Windows.Controls.TextBlock()
            t.Text = text
            t.Foreground = brush
            t.FontSize = size
            t.FontFamily = Media.FontFamily("Consolas")
            left, top = px(u_mm, v_mm)
            Windows.Controls.Canvas.SetLeft(t, left)
            Windows.Controls.Canvas.SetTop(t, top)
            canvas.Children.Add(t)

        def line(u0, v0, u1, v1, brush=DIM, thickness=1.0):
            ln = Shapes.Line()
            x0, y0 = px(u0, v0)
            x1, y1 = px(u1, v1)
            ln.X1, ln.Y1, ln.X2, ln.Y2 = x0, y0, x1, y1
            ln.Stroke = brush
            ln.StrokeThickness = thickness
            canvas.Children.Add(ln)

        def circle(u_mm, v_mm, dia_mm, brush):
            e = Shapes.Ellipse()
            d = max(3.0, dia_mm * scale)
            e.Width = e.Height = d
            e.Fill = brush
            x, y = px(u_mm, v_mm)
            Windows.Controls.Canvas.SetLeft(e, x - d / 2.0)
            Windows.Controls.Canvas.SetTop(e, y - d / 2.0)
            canvas.Children.Add(e)

        # --- concrete outline: b x h, straight from the inputs
        rect(b_mm, h_mm, CONCRETE, 2.0)

        # --- cover line. NOTE: this is A48's GAP 1 in the flesh -- A30
        # defines the outer stirrup rectangle as (b-2c) x (h-2c) but no core
        # function returns it, so the spike computes it here. In the real
        # renderer this MUST come from stirrups.outer_leg_dimensions_mm,
        # which A48 records as a required core addition. Left visible rather
        # than hidden, because it is the clearest possible argument for that
        # addition.
        rect(b_mm - 2 * v["cover"], h_mm - 2 * v["cover"],
             COVER_LINE, 1.0, dash=[4.0, 3.0])

        # --- stirrup centreline rectangle: FROM THE CORE
        st_w, st_h = centreline_leg_dimensions_mm(
            b_mm, h_mm, v["cover"], v["stirrup"]
        )
        rect(st_w, st_h, STIRRUP, 2.0)

        # --- bottom bars: u positions and layer offset, both FROM THE CORE
        offset_1 = first_layer_offset_mm(v["cover"], v["stirrup"], v["bar"])
        u_positions = corner_bar_u_positions_mm(
            b_mm, v["cover"], v["stirrup"], v["bar"], v["count"]
        )
        v_bottom = -(h_mm / 2.0) + offset_1
        for u_mm in u_positions:
            circle(u_mm, v_bottom, v["bar"], BAR)

        # --- one dimension line, to prove annotation works
        dim_v = -h_mm / 2.0 - 28.0 / max(scale, 1e-6)
        line(-b_mm / 2.0, dim_v, b_mm / 2.0, dim_v)
        line(-b_mm / 2.0, dim_v + 6.0 / scale, -b_mm / 2.0, dim_v - 6.0 / scale)
        line(b_mm / 2.0, dim_v + 6.0 / scale, b_mm / 2.0, dim_v - 6.0 / scale)
        label("b = {:.0f}".format(b_mm), -14.0 / scale, dim_v - 10.0 / scale)

        label("stirrup c/l {:.0f} x {:.0f}  (core)".format(st_w, st_h),
              -b_mm / 2.0, h_mm / 2.0 + 34.0 / scale, STIRRUP)
        label("offset_1 = {:.1f}  (core)".format(offset_1),
              -b_mm / 2.0, h_mm / 2.0 + 16.0 / scale, BAR)

    # ----------------------------------------------------------- image probe
    def _run_image_probes(self):
        """Three probes, reported rather than assumed."""
        here = os.path.dirname(__file__)
        lines = []

        # (1) relative Uri set from code -- what a XAML relative Source does
        try:
            src = framework.Imaging.BitmapImage(
                framework.Uri("probe.png", framework.UriKind.Relative)
            )
            self.probe_image.Source = src
            lines.append("[1] relative Uri from code      : LOADED "
                         "({}x{})".format(src.PixelWidth, src.PixelHeight))
        except Exception as ex:
            lines.append("[1] relative Uri from code      : FAILED "
                         "{}: {}".format(type(ex).__name__, ex))

        # (2) absolute Uri built from this script's folder -- the fallback
        try:
            abs_path = os.path.join(here, "probe.png")
            src2 = framework.Imaging.BitmapImage(
                framework.Uri(abs_path, framework.UriKind.Absolute)
            )
            lines.append("[2] absolute Uri from __file__  : LOADED "
                         "({}x{})".format(src2.PixelWidth, src2.PixelHeight))
            if self.probe_image.Source is None:
                self.probe_image.Source = src2
                lines.append("    (displayed via [2], since [1] failed)")
        except Exception as ex:
            lines.append("[2] absolute Uri from __file__  : FAILED "
                         "{}: {}".format(type(ex).__name__, ex))

        # (3) Source DECLARED IN XAML, in a throwaway window that is never
        # shown. Isolated deliberately: if LoadComponent throws on an
        # unresolvable path, it must not take the main window with it.
        try:
            probe_win = forms.WPFWindow("ImageProbe.xaml")
            declared = getattr(probe_win, "declared_image", None)
            if declared is not None and declared.Source is not None:
                lines.append("[3] Source declared in XAML     : LOADED "
                             "({})".format(declared.Source))
            else:
                lines.append("[3] Source declared in XAML     : loaded window "
                             "but Source is None")
        except Exception as ex:
            lines.append("[3] Source declared in XAML     : FAILED "
                         "{}: {}".format(type(ex).__name__, ex))

        self._image_lines = lines
        self.image_report.Text = "\n".join(lines)

    # ---------------------------------------------------------------- notes
    def _write_notes(self):
        self.notes_block.Text = "\n".join([
            "ISSUE #42 -- throwaway spike. Nothing here ships.",
            "",
            "If you are reading this inside Revit, these are already proven:",
            "",
            "  [OK] WPFWindow loaded SpikeWindow.xaml by bare filename from",
            "       inside a *.pushbutton folder.",
            "  [OK] TabControl rendered and you switched to this tab. This",
            "       had NO precedent in pyRevit's 187 shipped XAML files.",
            "  [OK] rft.core imported and is being called in a UI context.",
            "",
            "Check for yourself:",
            "",
            "  - Section sketch tab: type in any box. The canvas must redraw",
            "    and the status bar must report milliseconds. Try clearing a",
            "    box completely -- a half-typed number must not kill it.",
            "  - Image probe tab: the three results decide image-vs-vector.",
            "  - Resize the window: the canvas must rescale, not clip.",
            "",
            "Everything drawn in blue and red comes from rft.core, per A48.",
            "The grey dashed cover line does NOT -- it is computed in the",
            "renderer, which A48 forbids, and it is left visible on purpose",
            "as the argument for adding stirrups.outer_leg_dimensions_mm.",
        ])

    def report(self):
        output.print_md("### UI spike (#42) -- session result")
        output.print_md("- redraws: **{}**, mean **{:.1f} ms**, worst "
                        "**{:.1f} ms**".format(
                            self._redraws,
                            self._total_ms / max(self._redraws, 1),
                            self._worst_ms))
        output.print_md("- `WPFWindow` loaded `SpikeWindow.xaml` by bare "
                        "filename: **OK**")
        output.print_md("- `TabControl` rendered under pyRevit's injected "
                        "resources: **OK** (no precedent in shipped XAML)")
        output.print_md("- `rft.core` imported and called from the UI: **OK**")
        output.print_md("- bitmap path probes:")
        for line in self._image_lines:
            output.print_md("      " + line)


window = SpikeWindow()
window.ShowDialog()
window.report()
