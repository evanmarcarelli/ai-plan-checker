# California Building-Code Supersession — Research Brief

**Purpose:** Validate Architechtura's supersession model (`precedence.py`,
`amendments.py`, `adoption_map.yaml`) against primary law.
**Date:** 2026-06-25 · **Cycle in force:** 2025 Title 24 (effective 2026-01-01).
**Source priority:** leginfo.legislature.ca.gov, dgs.ca.gov/BSC, coastal.ca.gov,
hcd.ca.gov. Secondary law-firm/agency summaries are cited only to corroborate a
primary text, never as the sole authority. Anything not confirmable against a
primary source is tagged **UNVERIFIED**.

---

## Executive summary

1. **Cycle transition (2022 → 2025 Title 24).** The 2025 California Building
   Standards Code was **published July 1, 2025** and is **effective January 1,
   2026**. The 2022 edition governed permits applied for **2023-01-01 →
   2025-12-31**. The controlling edition is set by the **permit application
   (submittal) date**, not plan-check or issuance. The model's
   `prior_effective_until: 2025-12-31` and `effective 2026-01-01` are **correct**.
   But the model does **not** encode the "permit application date" rule anywhere,
   and `amendments.py` resolves by `as_of` date with **no documented convention**
   that `as_of` = application date.

2. **More-restrictive doctrine.** H&S **§17958.5 / §17958.7 / §18941.5** let a
   local jurisdiction amend the state code only with **express findings** of
   local **climatic, geological, or topographical** conditions, **filed with the
   BSC** (and HCD for housing); no amendment is operative until filed. Locals may
   be **more restrictive**; they may **not** be **less** restrictive than the
   state minimum. The model's `more_restrictive` default and the H&S 17958.5
   citation are **directionally correct**, but the model never enforces the
   "filed-with-BSC" precondition and has no field for the findings.

3. **State-preemption carve-outs.** ADU/JADU, SB 9, and Density Bonus law
   override conflicting **local zoning/development standards** — but each is a
   **partial** preemption (objective standards survive), and **none of them
   override the Coastal Act**. The Coastal Act itself is **not** a zoning
   preemption like the others — it is a **parallel permitting regime** (CDP)
   layered through certified LCPs. The model lumps `coastal_act` in with the
   zoning carve-outs, which mis-describes its mechanism.

4. **Overlay stacking.** Confirmed: **Coastal Zone** (CDP) and **WUI / Fire
   Hazard Severity Zone** (Chapter 7A → new CWUIC) requirements **add to** base
   requirements; they do not replace them. The model's `overlay` relationship
   and `_OVERLAY_LAYERS` are correct in principle, but `_OVERLAY_LAYERS` only
   contains `CA:Coastal` — **WUI/FHSZ has no overlay layer key**, so WUI
   provisions are not guaranteed to be treated as additive.

5. **Accessibility.** Confirmed: **ADA (2010 Standards)** and **CBC Ch. 11A/11B**
   both apply; the **stricter / greater-access** provision governs and both are
   retained. The model's `ada_independent` basis is **correct**.

**Biggest single defect:** the ADU carve-out cites the **wrong statute**. The
YAML says `Gov. Code 66310 et seq.` (and `precedence.py`'s docstring implies the
old regime). Operative ADU **standards** live at **Gov. Code §66314 et seq.**;
§66310–66313 are findings/definitions. The pre-2025 cite was §65852.2.

---

## Q1 — Cycle transition 2022 → 2025 Title 24

**Publication / effective dates.** The 2025 California Building Standards Code
(Title 24) was **published July 1, 2025**, **effective January 1, 2026**. The
prior 2022 edition was published July 1, 2022 and became effective January 1,
2023.
- BSC codes index: https://www.dgs.ca.gov/bsc/codes
- 2025 code-change hub: https://www.dgs.ca.gov/BSC/Resources/2025-Title-24-California-Code-Changes
- AHJ confirmations (secondary, corroborating the Jan 1 2026 date):
  Riverside County https://building.rctlma.org/news/2025-california-building-standards-code-effective-january-1-2026 ·
  City of Sonoma https://www.sonomacity.org/new-california-building-code-cycle-begins-january-1-2026/

**Permit-application-date rule.** The edition governing a project is the one in
effect on the **date the permit application is submitted**, not plan-check or
issuance, and not the construction start date. This is the consistently stated
transition rule.
- https://title24energy.com/when-do-title-24-updates-take-effect/
- https://www.permits-pipeline.com/post/the-2026-code-change-countdown-what-california-s-new-rules-mean-for-permit-expediters-architects
- **Statutory mechanism / 180-day rule:** local amendments + the applicable
  portions of the code become effective **180 days after publication** (H&S
  §18942(d) framing surfaced via §18941.5 text). The 2022 cycle window is
  therefore **2023-01-01 → 2025-12-31**.

**Intervening supplements / errata (do NOT change the governing edition, but DO
change content within a cycle):**
- The 2022 cycle had an **Intervening Supplement effective 2024-07-01** and an
  **erratum effective 2023-01-01**.
- The 2025 cycle ships with **errata effective 2026-01-01** and, notably, an
  **Emergency Supplement for the new Part 7 (Wildland-Urban Interface Code)**,
  effective 2026-01-01.
- Source: BSC codes index https://www.dgs.ca.gov/bsc/codes (supplement/errata
  listings). The CEBC corpus note in the YAML already references a "Jan 2026
  erratum," consistent with this.
- **UNVERIFIED:** the *exact* scope of the 2024-07-01 intervening supplement
  (which parts) was not pinned to a single primary page in this pass — flag
  before relying on intra-cycle 2022 content as of mid-2024.

**Takeaway for the model:** dates are right; the **governing-edition selector
key (= permit application date)** is the missing concept. `amendments.py`'s
`as_of` is the natural home for it but is undocumented as such, and there is no
edition-selection function that maps `application_date → edition_cycle`.

---

## Q2 — More-restrictive doctrine (H&S §17958.5, §17958.7, §18941.5)

**§17958.5 — authority to modify.** A city/county may make "such changes or
modifications in the requirements" of the code "as it determines … are
reasonably necessary because of local **climatic, geological, or topographical**
conditions." Text does not, on its face, limit modifications to "more
restrictive," but the broader scheme (below) caps the floor at the state
minimum.
- https://codes.findlaw.com/ca/health-and-safety-code/hsc-sect-17958-5/
- https://law.onecle.com/california/health/17958.5.html

**§17958.7 — express findings + filing precondition.** The governing body must
make an **express finding** that each modification is reasonably necessary
because of local climatic/geological/topographical conditions; the finding is a
public record; **a copy of the finding and the modification must be filed with
the California Building Standards Commission**; and **"no modification or change
shall become effective or operative for any purpose until the finding and the
modification or change have been filed"** with the BSC. The BSC may reject a
change filed without a finding.
- https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=HSC&sectionNum=17958.7.
- https://codes.findlaw.com/ca/health-and-safety-code/hsc-sect-17958-7/

**§18941.5 — preserves "more restrictive" local authority.** "Neither the State
Building Standards Law … nor the application of building standards … shall limit
the authority of a city, county, or city and county to establish **more
restrictive building standards** … reasonably necessary because of local
climatic, geological, or topographical conditions," **subject to the §17958.7
findings/filing**. Local amendments become effective **180 days after
publication** of the code (or later date set by the commission).
- https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=HSC&sectionNum=18941.5.
- https://law.justia.com/codes/california/code-hsc/division-13/part-2-5/chapter-4/section-18941-5/

**More vs. less restrictive.** Locals may be **MORE** restrictive (with findings
+ filing). They may **NOT** drop **below** the state building-standard minimum —
the state floor is uniform statewide; §18941.5's grant is expressly to
*establish more restrictive* standards.
- BSC "Guide for Local Amendments of Building Standards":
  https://www.dgs.ca.gov/BSC/Resources/Frequently-Asked-Questions

**2025–2031 residential overlay (NEW, easy to miss).** AB 130 (2025) added a
constraint: from **2025-10-01 through 2031-06-01**, local **residential**
building-standard modifications are restricted unless they fit narrow exceptions
(substantially equivalent to prior standards, emergency health/safety, home
hardening, or admin practices reviewed within 60 days). This narrows the
more-restrictive doctrine for housing during that window.
- §17958.5(c) / §18941.5 text (above) reflect this.
- https://www.bhfs.com/insight/ab-130-places-new-limitations-on-building-code-updates-for-residential-buildings/

**Takeaway:** the model's `more_restrictive` default is right, and citing H&S
17958.5 is right. Gaps: (a) no representation of the **findings/filing
precondition** (an amendment not filed with BSC is legally inoperative — the
model would still apply it); (b) no awareness of the **AB 130 residential
window**; (c) no explicit "**locals can't go below the state floor**" guard.

---

## Q3 — State-preemption carve-outs (where LOCAL does NOT govern)

### ADU / JADU — **Gov. Code §66314 et seq.** (recodified from §65852.2)

- **Recodification:** SB 477 (2023, urgency, **organizational not substantive**)
  relocated ADU law from the old §65852.x sections into **Gov. Code Title 7,
  Div. 1, Chapter 13 (§§66310–66342)**, operative **2025-01-01**. Findings =
  §§66310–66312; definitions = §66313; **operative standards = §§66314–66332**.
  - https://bbklaw.com/resources/la-041024-sb-477-relocated-and-consolidated-state-adu-law-into-a-new-government-code-ch
  - https://law.justia.com/codes/california/code-gov/title-7/division-1/chapter-13/article-1/section-66310/
  - HCD ADU Handbook (2025/2026): https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/adu-handbook-update.pdf
- **What it preempts:** §66315/§66314 set the **maximum** standards a local
  agency may apply; "no additional standards … shall be used or imposed." Locals
  cannot impose owner-occupancy (with narrow exceptions), minimum lot size, or
  FAR/lot-coverage/open-space/setback rules that block at least an 800 sf ADU
  with 4-ft side/rear setbacks. Some ADUs (e.g., §66323) are ministerial with
  **no** reference to local development standards.
- **Supersession relationship:** **state overrides conflicting local zoning**
  for the ADU itself. **But not building-safety standards** — an ADU must still
  meet the CBC/CRC. Carve-out is **zoning-scoped**, which the model gets right.

### SB 9 — **Gov. Code §65852.21 (two-unit)** + **§66411.7 (urban lot split)**

- Effective 2022-01-01. Ministerial approval of a two-unit development / urban
  lot split on single-family-zoned lots; CEQA does not apply to the ministerial
  decision.
  - https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202120220SB9
  - HCD SB 9 fact sheet: https://www.hcd.ca.gov/sites/default/files/docs/planning-and-community/sb-9-fact-sheet.pdf
- **Partial preemption — objective standards survive.** §65852.21(b)(1) lets a
  local agency impose **objective zoning, subdivision, and design-review
  standards** *so long as* they don't physically preclude two ≥800 sf units.
  So SB 9 is **not** a clean "state replaces local" — local objective standards
  still bind.
  - https://codes.findlaw.com/ca/government-code/gov-sect-65852-21/
- **Does NOT touch the Coastal Act.** **§65852.21(l):** *"Nothing in this
  section shall be construed to supersede or in any way alter or lessen the
  effect or application of the California Coastal Act of 1976."* (PRIMARY.)
  SB 9 also excludes historic-district contributing structures, and is
  constrained near ESHA / habitat for protected species.
  - Coastal Commission SB 9 memo: https://documents.coastal.ca.gov/assets/rflg/sb9-memo.pdf

### State Density Bonus Law — **Gov. Code §65915**

- Grants extra density + **concessions/incentives** and **waivers** of
  development standards that would physically preclude the bonus project. A local
  agency cannot apply a development standard that physically precludes the
  permitted density/concessions; waivers must be granted where a standard would
  physically preclude the project.
  - https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=GOV&sectionNum=65915
  - https://codes.findlaw.com/ca/government-code/gov-sect-65915/
- **Supersession relationship:** overrides specific **local development
  standards** on request (concession/waiver), **not** wholesale. Denials require
  substantial-evidence findings (no cost savings / specific adverse health-safety
  impact / contrary to law). Does **not** override the Coastal Act, building
  safety code, or state/federal law.

### California Coastal Act — **Pub. Res. Code §30000 et seq.** (DIFFERENT MECHANISM)

- **Not a zoning preemption like the three above.** The Coastal Act is a
  **separate, parallel permitting regime**: development in the **coastal zone**
  needs a **Coastal Development Permit (CDP)**. Where a local **Local Coastal
  Program (LCP)** is certified by the Coastal Commission, CDP authority is
  **delegated to the local government** and the **certified LCP is the standard
  of review**; the Commission retains **appeal jurisdiction** over defined
  geographies and project types. Where no LCP is certified, the **Commission
  issues CDPs directly**.
  - PRC §30000 et seq.: https://law.justia.com/codes/california/code-prc/division-20/chapter-1/section-30000/
  - Coastal Act full text (binary PDF; cite the codified sections, not this PDF):
    https://www.coastal.ca.gov/coastact.pdf
  - LCP framework: https://www.coastal.ca.gov/lcp/lcp-info/
- **Supersession relationship:** the Coastal Act / certified LCP **adds a
  permit and a substantive review layer ON TOP of** local zoning and the
  building code. It **supersedes housing-streamlining statutes** (SB 9, ADU,
  density bonus) **to the extent they'd erode coastal protection** — those
  statutes expressly defer to it (see §65852.21(l); ADU/coastal memo below).
  It does **not** replace the building code.
  - ADU + Coastal Act guidance: https://documents.coastal.ca.gov/assets/rflg/ADU-Memo.pdf
  - ADUs in the coastal zone still generally need a CDP (AB 462 streamlines, 60-day
    LCP decision, removes Commission appeal of ADU CDPs):
    https://bbklaw.com/resources/la-110725-governor-newsom-signs-four-new-accessory-dwelling-unit-bills

**Carve-out hierarchy (net):**
`Coastal Act` ⟶ outranks ⟶ `SB 9 / ADU / Density Bonus` ⟶ outrank ⟶ `local
zoning`. None of these override the **building-safety** standards; the
more-restrictive doctrine (Q2) governs those independently.

---

## Q4 — Overlay stacking (Coastal + WUI add, not replace)

**Coastal:** confirmed additive — a coastal project needs its base building
permit **and** a CDP; LCP standards are layered on, zoning still applies except
where the LCP modifies it. (Sources in Q3.)

**WUI / Fire Hazard Severity Zone (Chapter 7A):**
- Chapter 7A applies to new buildings located in **any FHSZ** (SRA Moderate/
  High/Very-High; LRA Very-High) **or** designated WUI Fire Area, and its
  material/construction standards are expressly **"in addition to"** the base
  roof/wall/exterior standards elsewhere in the CBC — i.e., **additive**.
  - https://usmadesupply.com/resources/building-codes-standards/cbc-7a
  - https://www.brandguardvents.com/technical-hub/chapter-7a-of-the-california-building-code/
- **2025-cycle structural change (IMPORTANT, model-relevant):** under the **2025
  Title 24 cycle (effective 2026-01-01)**, the BSC **deleted Chapter 7A from the
  CBC** and **relocated those provisions into the new California Wildland-Urban
  Interface Code (CWUIC), Title 24 Part 7**; CBC Ch. 7A now holds only a pointer
  (CBC §101.4.8 → CWUIC). The new Part 7 shipped with an **Emergency
  Supplement**.
  - https://usmadesupply.com/resources/building-codes-standards/cbc-7a
  - Berkeley CWUIC adoption (corroborating, secondary):
    https://berkeleyca.gov/sites/default/files/documents/2025-12-02%20Item%2041%20Adoption%20of%20and%20Amendments.pdf

**Takeaway:** stacking is confirmed. The model is missing **WUI as an overlay
layer** entirely, and any text that says "Chapter 7A" is **edition-stale** for
2025 (now CWUIC / T24 Part 7).

---

## Q5 — Accessibility (ADA 2010 vs CBC 11A/11B)

- **Both apply; stricter/greater-access governs.** In California you must satisfy
  **both** the federal ADA (2010 Standards) and the CBC (Ch. 11A residential
  multifamily / 11B public/commercial). Where they differ, the provision giving
  **greater accessibility** controls; neither is "chosen" over the other. CBC
  11B is frequently **more** stringent than the 2010 ADA. The Unruh Act makes an
  ADA violation a state-law violation, reinforcing dual compliance.
  - https://www.meltplan.com/blogs/california-accessibility-code-navigating-cbc-chapter-11a-11b-and-ada-conflicts
  - https://www.coreyandpartners.com/post/understanding-the-differences-2022-cbc-chapter-11b-vs-2010-ada-standards
  - **UNVERIFIED (primary):** the "greater access governs" rule is universally
    stated in practice guides but is not a single CA statute; it derives from
    ADA §§ being a federal floor + CBC being state law + Unruh. Treat as
    well-settled doctrine, not a single citable section.

**Takeaway:** the model's `ada_independent` basis (stricter governs, both
retained) is **correct**. One refinement: 11A (residential) vs 11B
(public/commercial) selection is **occupancy-driven**; the model treats
accessibility as one category and should not assume 11B for residential.

---

## Cross-check against the current model

Legend: ✅ matches law · ⚠️ partially wrong / incomplete · ❌ wrong.

### `adoption/adoption_map.yaml`

| Item | Finding |
|---|---|
| `edition_cycle: 2025 Title 24` eff 2026-01-01; `prior_effective_until: 2025-12-31` | ✅ correct (Q1). |
| ADU carve-out `statute: "Gov. Code 66310 et seq."` | ⚠️ **wrong anchor.** Operative ADU standards = **§66314 et seq.** §66310–313 are findings/defs. Pre-2025 cite was §65852.2. Use `Gov. Code §66314 et seq. (recodified from §65852.2 by SB 477, operative 2025-01-01)`. |
| SB 9 carve-out `65852.21 / 66411.7` | ✅ section numbers correct, but `summary` overstates it: SB 9 lets locals keep **objective** standards (not full preemption). |
| Density bonus `65915` | ✅ correct. |
| `coastal_act` listed under `precedence.carveouts` with `topic: zoning`, summary "Coastal Act / certified LCP governs coastal-zone land use; a CDP is required." | ⚠️ **mechanism mislabeled.** Coastal Act is a **parallel CDP regime / overlay**, not a zoning-preemption peer of ADU/SB9. It also **outranks** the other three carve-outs (§65852.21(l)). Modeling it only as a `zoning` carve-out understates it. |
| LA `zoning: relationship: replaces, preempted_by: [adu, sb9, density_bonus]` | ⚠️ `replaces` is fine for "local zoning is the operative land-use law"; but the SB 9/density-bonus relationship is **partial** preemption, and **coastal_act is missing** from LA's `preempted_by` even though LA has coastal communities (Venice, San Pedro, Pacific Palisades). |
| Malibu `zoning … preempted_by: [coastal_act]` | ✅ correct that Malibu zoning yields to the Coastal Act / certified LCP. |
| `overlays: [..., coastal, very_high_fhsz, ...]`; only `CA:Coastal` is a corpus layer key | ⚠️ **WUI/FHSZ overlay has no `corpus_layer_key` and no precedence-side overlay tag.** Coastal gets `CA:Coastal`; WUI gets nothing equivalent. |
| Any "Chapter 7A" framing for fire/WUI | ⚠️ **edition-stale for 2025.** Now **CWUIC, T24 Part 7** (CBC Ch. 7A is a pointer). |
| 2022 intervening supplement (2024-07-01) | ⚠️ not represented; matters only for permits applied 2024-07-01 → 2025-12-31 needing intra-cycle content. **UNVERIFIED scope.** |

### `precedence.py`

| Item | Finding |
|---|---|
| Docstring rule (a): "more restrictive governs (H&S 17958.5)" | ✅ correct doctrine. Missing: the **filing-with-BSC precondition** (§17958.7) — an unfiled local amendment is legally inoperative; `amendments.py._live()` gates only on `needs_review`/`effective_date`, not on "filed." |
| Docstring rule (b): zoning local-governs except ADU/SB9/density/Coastal preempt | ⚠️ correct list, but treats all four as same-tier zoning preemptions. Coastal is different (overlay + outranks the others). |
| `_OVERLAY_LAYERS = {"CA:Coastal"}` | ❌ **incomplete.** WUI/FHSZ is also an additive overlay and is absent. A WUI provision won't be recognized as `overlay_stacks` via this set. |
| `_matching_carveout()` only matches `meta.topic == "zoning"` | ⚠️ since `coastal_act` is tagged `topic: zoning` in the YAML, it *will* match here — but that's the **wrong mechanism**: Coastal should drive an **overlay/CDP** path, not a zoning-replacement path. |
| `stricter_of()` more-restrictive numeric logic + `needs_review` fallback | ✅ sound and conservative. No legal defect. The "locals can't go below the state floor" rule is **implicit** (it picks the stricter) but not **asserted** — a malformed local "max" that is *less* strict would silently win as "smallest maximum." Consider a floor guard for building-safety categories. |
| Accessibility `ada_independent` (stricter governs, both retained) | ✅ correct (Q5). |
| `_active_carveouts()` ADU/SB9/density via text regex; coastal via GIS overlay | ✅ reasonable. ADU regex is fine; just note the **statute string** is what's wrong, not the detection. |

---

## Proposed changes (NOT yet applied)

> These are suggestions only. `adoption_map.yaml` and `precedence.py` were **not**
> edited. Each diff is illustrative; confirm exact YAML/field names before
> applying.

### 1. Fix the ADU carve-out statute (highest-confidence correction)

```diff
# adoption_map.yaml — precedence.carveouts
     - id: adu
-      statute: "Gov. Code 66310 et seq."
+      statute: "Gov. Code 66314 et seq. (recodified from 65852.2 by SB 477, operative 2025-01-01)"
       topic: zoning
       summary: "State ADU law preempts local zoning that would preclude a conforming ADU/JADU."
+      # Findings/defs live at 66310-66313; operative standards at 66314-66332.
```

### 2. Reclassify the Coastal Act as an overlay/CDP regime, not a zoning peer

```diff
# adoption_map.yaml — precedence.carveouts
     - id: coastal_act
       statute: "Pub. Res. Code 30000 et seq."
-      topic: zoning
+      topic: overlay          # parallel CDP regime layered on top; NOT a zoning replacement
       summary: "Coastal Act / certified LCP governs coastal-zone land use; a CDP is required."
+      outranks: [adu, sb9, density_bonus]   # Gov. Code 65852.21(l): housing statutes defer to the Coastal Act
+      applies_when: "site is inside the Coastal Zone"
```
…and in `precedence.py`, route a `topic: overlay` carve-out through the
`overlay_stacks` path (additive) instead of `state_preempts_local`
(zoning-replacement). Keep `_matching_carveout()` filtering on `topic == "zoning"`
so Coastal no longer hijacks the zoning branch.

### 3. Add WUI/FHSZ as a first-class additive overlay

```diff
# precedence.py
-_OVERLAY_LAYERS = {"CA:Coastal"}
+_OVERLAY_LAYERS = {"CA:Coastal", "CA:WUI"}   # WUI/FHSZ (CWUIC / T24 Part 7) is additive, like Coastal
```
…and give WUI jurisdictions a `CA:WUI` entry in `corpus_layer_keys` (parallel to
`CA:Coastal`), driven by the existing `very_high_fhsz` overlay signal.

### 4. De-stale the fire/WUI references for the 2025 cycle

```diff
# adoption_map.yaml comments + any "Chapter 7A" text
-  # ... CBC Chapter 7A (WUI) ...
+  # ... 2025 cycle: WUI relocated to California Wildland-Urban Interface Code
+  #     (CWUIC), Title 24 Part 7 (Emergency Supplement, eff. 2026-01-01);
+  #     CBC Ch. 7A is now a pointer (CBC 101.4.8). 2022 cycle still uses CBC Ch. 7A.
```
(Also update `precedence.py` docstring line `(c) Overlays` example if it names 7A.)

### 5. Encode the §17958.7 "filed-with-BSC" precondition + the application-date selector

```diff
# amendments.py — _live(): a local amendment is operative ONLY if filed with BSC
   for a in amendments:
       if a.get("needs_review", True):
           continue
+      # H&S 17958.7: no local modification is operative until findings + change
+      # are filed with the BSC. Treat unfiled deltas as not-in-force.
+      if a.get("filed_with_bsc") is False:
+          continue
       eff = a.get("effective_date")
       if as_of and eff and str(eff) > str(as_of):
           continue
```
Plus a one-line convention note that `as_of` **= the permit application
(submittal) date** (the edition selector, per Q1), and ideally an
`edition_for_application_date()` helper mapping `application_date → edition_cycle`
(2022 if < 2026-01-01 and ≥ 2023-01-01; 2025 if ≥ 2026-01-01).

### Secondary (lower priority)
- Add `coastal_act` to `ca_los_angeles_city.zoning.preempted_by` (LA has coastal
  communities), or better, attach Coastal via the overlay path.
- Soften the SB 9 / density-bonus carve-out summaries to "**partial** preemption
  — local **objective** standards still apply."
- Note the **AB 130 (2025) residential window** (2025-10-01 → 2031-06-01) that
  constrains new local residential amendments — relevant when validating a local
  residential delta's legality.
- Accessibility: select **11A (residential) vs 11B (public/commercial)** by
  occupancy rather than defaulting to 11B.

---

## Unverified / open items (flagged, not asserted)
- Exact **scope** of the 2022-cycle Intervening Supplement (2024-07-01) — which
  parts changed — not pinned to a single primary page this pass.
- The "**greater-access governs**" accessibility rule is settled practice
  doctrine (ADA floor + CBC + Unruh), **not** a single citable statute section.
- Per-city LCP **certification status / year** in the YAML (Santa Monica "not
  fully certified," Manhattan Beach 1994, Long Beach 1980, etc.) was **not**
  re-verified in this pass — those `[verify]` tags remain open.
- Whether `coastal_act` should remain selectable as a "carveout" at all, vs.
  being modeled purely as the `CA:Coastal` overlay layer, is a design call for
  the team.
