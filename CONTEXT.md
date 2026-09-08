# Project Context — RFT Beam Detailing Tool

## Standing rule: the spec is the source of truth

All detailing logic (development length & anchorage, stirrup distribution,
main bar layer offsets, crack/skin reinforcement, bar spacing rules, stirrup
closure types) is governed by
[`00.Technical Material/beam_rebar_detailing_spec_v2.docx`](00.Technical%20Material/beam_rebar_detailing_spec_v2.docx).

**Revision 2 is the source of truth.** `beam_rebar_detailing_spec.docx`
(revision 1) is kept only as the historical baseline — do not implement from
it. Rev 2 incorporates 40 amendments from the Wayfinder cycle, each traced to
its deciding ticket in [`docs/spec-amendments.md`](docs/spec-amendments.md).

- Every rule implemented in code must trace back to a numbered section of
  the spec (e.g. "per §2.1", "per §6.2"). Do not invent detailing rules that
  aren't in the spec — if a gap is found, it becomes a Grill-type decision
  ticket, not a silent guess.
- If a future change conflicts with the spec, the spec wins unless the user
  explicitly amends it first (and the doc is updated to match).

### Spec §9 open items — status after the Wayfinder cycle (2026-09-08)

1. **Bottom bar anchorage bend geometry (`a_btm`, §2.2)** — **CLOSED.**
   Confirmed correct as written; rationale recorded in rev 2 §2.2.
2. **Multi-span beam behavior** — **STILL DEFERRED.** Single-span is the hard
   scope boundary. Do not propose multi-span features unless the user raises
   them. The tool should warn on, or refuse, a beam in a continuous run
   rather than silently detailing it as simply supported.
3. **Stirrup leg dimensioning formulas (§7)** — **CLOSED for the outer
   perimeter** (rev 2 §7.1). The **inner loop of stirrup type 3** remains
   undefined, which is why **type 3 is parked** and the stirrup type input is
   (1, 2, 4) in v1.

### Residual questions R1–R6 — must not be guessed

Rev 2 §11 lists six questions the cycle deliberately left open. Any ticket
touching one of them must surface it as an explicit acceptance criterion and
get an answer from the user — it may **not** be resolved by assumption, and
such a ticket may not be marked `ready-for-agent` until it is.

## Standing rule: no live Revit host

Nothing in this environment can execute Revit API code, so no rebar logic can
be verified by running it. Every API decision in rev 2 §10 rests on
documentation and is flagged unverified.

Consequently, **any ticket touching Revit-API-dependent logic requires a
mock-object simulation write-up** demonstrating the logic is correct before it
can close in review. That write-up is the actual safety net here, not optional
polish.

### Mock fakes must declare unverified API shapes

Mock objects are written to match the API shape the adapter *assumes*. A green
test suite therefore proves the adapter's **logic** is self-consistent — it does
**not** prove the real Revit API has those members, signatures or return types.
When an assumed shape is wrong, the tests pass and the tool still throws on its
first real run.

So: every fake standing in for an API whose shape is not
documentation-confirmed **must carry an inline `SHAPE UNVERIFIED` note** naming
what is assumed and what the documentation suggests instead. Never let a
passing suite be mistaken for API validation. See the header of
`tests/fake_revit_api.py` for the running list.

The load-bearing unknown: if `RebarStyle.StirrupTie` disallows 180° hooks, the
mild-steel hook decision (rev 2 §7.3) must be revisited.
