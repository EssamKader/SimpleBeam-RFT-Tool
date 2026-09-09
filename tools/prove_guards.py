# -*- coding: utf-8 -*-
"""Re-prove EVERY text-based guard by mutation.

Two of them were found to be silently broken (a regex word boundary written
into the file as a literal backspace byte), and a third was too coarse to
notice one of two calls being removed. A guard that has never been shown to
fail has not been tested -- it has only been written.

Of the first run's three "misses", two were bad MUTATIONS rather than weak
guards: one commented the wrong line, one targeted the wrong method. That
distinction matters -- a mutation that does not reintroduce the defect
proves nothing either way, and reading it as a broken guard sends you
rewriting checks that already work.
"""
import io
import subprocess

SCRIPT = ("RFTBeamDetailing.extension/RFT Beam Detailing.tab/"
          "Detail Beam.panel/Detail Beam.pushbutton/script.py")
BUNDLE = ("RFTBeamDetailing.extension/RFT Beam Detailing.tab/"
          "Detail Beam.panel/Detail Beam.pushbutton/bundle.yaml")
T = "tests/test_detail_beam_xaml.py::"

GEOM_ANCHOR = "        # an anchor.\n        self.geometry_mm = None"
CATCH_ANCHOR = ("        except Exception as ex:\n"
                "            # NEVER let this reach the ExternalEvent handler")
CATCH_MUTANT = ("        except ValueError as ex:\n"
                "            # NEVER let this reach the ExternalEvent handler")

CASES = [
    (SCRIPT, "review.crack_bars.requested", "review.crack.requested",
     "test_every_review_attribute_the_script_uses_exists",
     "wrong derivation attribute (the rc4 live failure)"),

    (SCRIPT, "    window.show()", "    window.ShowDialog()",
     "test_the_window_is_never_shown_modally",
     "modal window via ShowDialog"),

    (SCRIPT, "    window.show()", "    window.show_dialog()",
     "test_the_window_is_never_shown_modally",
     "modal via show_dialog (the branch that never matched)"),

    (SCRIPT, GEOM_ANCHOR, "        # an anchor.",
     "test_every_beam_scoped_attribute_is_cleared_on_pick",
     "beam-scoped state left stale on re-pick"),

    (SCRIPT, "        if not review.any_requested:\n            return missing\n", "",
     "test_place_preflight_consults_the_same_derivation_that_enables_it",
     "Place guard ignoring the derivation"),

    (BUNDLE, "engine:\n  persistent: true\n", "",
     "test_modeless_window_declares_a_persistent_engine",
     "no persistent engine (the rc2 live failure)"),

    (SCRIPT, "core_plan.face_layer_plans(", "hand_rolled_layer_offsets(",
     "test_report_and_placement_both_use_the_shared_plan",
     "report recomputing ONE of its plan calls by hand"),

    (SCRIPT, "core_plan.crack_plan(", "hand_rolled_crack_plan(",
     "test_report_and_placement_both_use_the_shared_plan",
     "placer recomputing the crack plan by hand"),

    (SCRIPT, CATCH_ANCHOR, CATCH_MUTANT,
     "test_dispatched_work_cannot_fail_silently",
     "dispatch wrapper narrows what it catches"),
]

missed = []
for path, find, replace, test, label in CASES:
    original = io.open(path, encoding="utf-8").read()
    if find not in original:
        print("%-56s ANCHOR MISSING" % label)
        missed.append(label)
        continue
    try:
        io.open(path, "w", encoding="utf-8", newline="\n").write(
            original.replace(find, replace, 1))
        rc = subprocess.call(["python", "-m", "pytest", T + test, "-q"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    finally:
        io.open(path, "w", encoding="utf-8", newline="\n").write(original)
        assert io.open(path, encoding="utf-8").read() == original, path
    if rc == 0:
        missed.append(label)
    print("%-56s %s" % (label, "caught" if rc else "*** MISSED ***"))

print("")
print("guards proven: %d of %d" % (len(CASES) - len(missed), len(CASES)))
if missed:
    raise SystemExit("NOT PROVEN: %s" % missed)
