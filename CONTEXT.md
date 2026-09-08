# Project Context — RFT Beam Detailing Tool

## Standing rule: the spec is the source of truth

All detailing logic (development length & anchorage, stirrup distribution,
main bar layer offsets, crack/skin reinforcement, bar spacing rules, stirrup
closure types) is governed by
[`00.Technical Material/beam_rebar_detailing_spec.docx`](00.Technical%20Material/beam_rebar_detailing_spec.docx).

- Every rule implemented in code must trace back to a numbered section of
  the spec (e.g. "per §2.1", "per §6.2"). Do not invent detailing rules that
  aren't in the spec — if a gap is found, it becomes a Grill-type decision
  ticket, not a silent guess.
- If a future change conflicts with the spec, the spec wins unless the user
  explicitly amends it first (and the doc is updated to match).

### Open items in the spec (§9) — must resolve before implementing that part

These are **not yet finalized** and must not be implemented from guesswork:

1. **Bottom bar anchorage bend geometry (`a_btm`, §2.2)** — the placeholder
   formula mirrors the top bar's logic by convention but has not been
   independently confirmed against a sketch.
2. **Multi-span beam behavior** — this spec covers **single-span only**.
   Multi-span is explicitly out of scope until a follow-up spec exists.
3. **Stirrup leg dimensioning formulas (§7)** — stirrup *type* (closure/hook
   style, 1–4) is defined, but the actual leg-length formulas (perimeter
   minus cover, per type) are referenced conceptually only, not yet reduced
   to explicit formulas.

Any ticket touching one of these three areas must resolve the underlying
question (via a Grill ticket with the user, or an update to the spec doc)
before it can be marked `ready-for-agent`.
