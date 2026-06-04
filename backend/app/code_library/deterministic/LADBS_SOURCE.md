# LADBS SFD rules — provenance

`ladbs_rules.py` was learned from a **real LADBS plan-check correction set**:
a single-family-dwelling **fire rebuild in Pacific Palisades (City of Los
Angeles)**, 158 enumerated corrections across the examiner's standard
`PC/STR/Corr.Lst.20` checklist. The source documents (plan set, scanned
correction sheet, architect response R1) are **private** and are NOT stored in
the repo. Everything below is the de-identified rule knowledge extracted from
them.

## Why this matters

These are the LA-specific completeness items a LADBS examiner checks on an SFD
that the generic IBC/CRC baseline does **not** cover — the "LADBS moat". They
are the difference between a generic code checker and one that reproduces what
a real LA examiner flags.

## Correction taxonomy (examiner's structure)

| Section | Theme | Sample corrections → rule |
|---|---|---|
| Part 1 | General / Admin | signatures, title-block info, anti-graffiti → `LADBS-SFD-ANTIGRAFFITI` |
| Part 2 | **Residential Floor Area (RFA)** | RFA summary, attic >7ft counts / >14ft double, porch rules → `LADBS-SFD-RFA` |
| Part 3 | **Height & Encroachment Plane** | Datum Point, height to natural grade → `LADBS-SFD-DATUM`, `-NATGRADE` |
| Green Building | CALGreen / GRN forms | GRN 1/4/11/16/18R, flow rates, cool roof, EV raceway, exhaust → `LADBS-SFD-GRN*`, `-COOLROOF`, `-EV-RACEWAY`, `-EXHAUST` |
| FHSZ checklist | WUI (Very High FHSZ) | CWUIC per LAMC Ch.V Art.7.1, LAMC 91.7207 → `LADBS-SFD-WUI`, `-HILLSIDE-FIRE` |
| Additional | Fire-rebuild EO | EO-1/EO-8 eligibility, footprint existing-vs-proposed, sprinklers → `LADBS-SFD-EO-ELIGIBILITY`, `-FOOTPRINT`, `-SPRINKLER` |

## What is / isn't machine-checkable

- **Deterministically checkable (the 19 rules here):** "is the required LA
  note / calc / form present on the plans?" — keyword-presence completeness
  checks, `requires_citation=False`. These reproduce the examiner's
  *completeness* corrections.
- **Needs extracted values (not yet rules):** RFA value vs. max allowed,
  height vs. limit, encroachment-plane geometry, backup-aisle encroachment —
  require parsing dimensioned values off the drawings, a future ticket.
- **Needs judgment / external data:** clearance signoffs, geology-report
  approval, MWELO landscape thresholds — examiner/agency dependent.

## Validation

`scripts/eval/cases/ladbs-sfd-palisades-rebuild.json` is the de-identified
eval case built from this correction set: it models the as-submitted plan
(missing the flagged items) and asserts the engine reproduces the examiner's
calls. Current result: **F1 = 1.000** (18 flagged items caught, 0 false
positives).

**Honest caveat:** the rules and that eval case were derived from the same
correction set, so F1=1.0 confirms the rules fire *as designed* — it is not
yet proof the engine catches these on the raw 1040-page plan PDF. That
stronger test (extract the real plan set → run the full pipeline → diff
against the 158 corrections) is the next validation step and needs PDF
extraction + LLM credits.
