# RFT Beam Detailing Tool

A pyRevit / Revit API tool for automated **simple beam rebar (RFT) detailing**
— single-span, rectangular concrete beams. Modeled after the workflow of
CADS Rebar Extensions for Revit, built from first principles.

This tool performs **pure detailing logic** (bar geometry, placement,
quantities) with no flexural or shear design calculation — bar sizes,
counts, and base dimensions are user inputs.

## Scope

- Development length & end anchorage (top/bottom bar hooks into supports)
- Stirrup distribution across 3 zones (dense/dense/normal)
- Main bar layer offsets (cross-section)
- Crack/skin reinforcement for deep beams (h > 700 mm)
- Bar spacing rules (corner-bar rule, min clear spacing, multi-layer)
- Stirrup closure/hook types (4 variants, CADS-aligned)

Full technical spec:
[`00.Technical Material/beam_rebar_detailing_spec.docx`](00.Technical%20Material/beam_rebar_detailing_spec.docx)

See [CONTEXT.md](CONTEXT.md) for standing project rules.

## Status

Early scoping stage — see open GitHub issues for current tickets.
