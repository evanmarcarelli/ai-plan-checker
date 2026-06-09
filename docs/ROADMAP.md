# Plan Room AHJ — Roadmap

> **Status:** Active execution doc. Updated as tickets ship.
> **Last updated:** 2026-06-02
> **Owner:** Evan Marcarelli

## Strategic context

`docs/PILOT_BRIEF.md` and `docs/ARCHITECTURE.md` lock this codebase to AHJ
(city building department) customers. **As of 2026-06-02 that lock is
overridden:** architect-firm-focused features are now in scope alongside the
AHJ pilot. The two audiences share ~80% of the engine (extractor, rule eval,
corpus, citation gate, PDF annotation). They diverge mainly in UX (multi-
tenant reviewer queue vs. single-firm upload-and-go) and in pricing.

This roadmap orders the work so dual-use features ship first — they pay off
on both customer paths — then audience-specific work is sequenced last.

The locked PILOT_BRIEF Hard NOs (no 99% trap, no Title 24 prescriptive
energy checker, no Sonnet+Opus voting, no eval set > 500 cases) remain in
force. Architect-focused work has to clear the same accuracy bar.

---

## Sequencing principles

1. **Demo moment first.** P3 (PDF annotation end-to-end) is the
   single highest-leverage user-visible feature. Nothing in this list
   matters as much as it working cleanly.
2. **Dual-use before audience-specific.** Features that serve both AHJ
   reviewers and architects ship before features that only serve one.
3. **Trust before reach.** P5 (audit trail) and the existing citation
   gate (Part 5, shipped) are the floor — without them a wrong citation
   loses the customer permanently.
4. **Knowledge layer is the moat.** P2 (LADBS-specific knowledge) is
   what makes PhiCodes 10× better than UpCodes Copilot. Highest long-term
   value, longest build time.
5. **Pivot work last.** P1 (architect-side UX flip) is the largest
   single-audience deliverable. Build it once the foundation is solid.

---

## P3 — PDF annotation end-to-end *(in flight)*

**Why first:** The components shipped (commit `94b7896`) but render no
highlights because `text_blocks` is never populated and the queue page
doesn't sign PDF URLs. This is "75% built, 25% wired" — finishing it
unlocks the demo moment for both audiences.

| Ticket | Scope | Effort | Status |
|---|---|---|---|
| **P3.a** | Server-side text_blocks producer using pdfjs-dist. Runs on upload or first triage; writes `[{page, text, bbox:{x,y,w,h}, sheet?}]` array into `submittal_files.text_blocks`. | 2–4 days | next up |
| **P3.b** | Signed Supabase Storage URL flow in `queue/[id]/page.tsx`. Server component mints a 1-hour signed URL for the submittal's primary PDF and passes it to FindingCard. | 0.5–1 day | pending P3.a |
| **P3.c** | Replace the inline finding rendering in `queue/[id]/page.tsx` with `<FindingCard>`. Map `TriageFinding` → `FindingForCard`. | 1 day | pending P3.b |
| **P3.d** | Ambiguity clarification loop. Yellow boxes are clickable; reviewer answers question inline; answer writes back to scope.evidence; partial re-triage runs only affected rules. | 1–2 weeks | pending P3.c |

**Success metric:** Reviewer drops a multi-sheet planset, sees a finding
list, clicks one, viewer jumps to the correct page with a red box on the
exact code-analysis row that triggered the finding. End-to-end demo runs
in under 8 minutes against a real LADBS planset.

**Open questions:**

- Where does the text_blocks producer run? Edge Function on upload is
  simpler but slow for 50-page sets. A separate worker via Supabase
  Cron + background job is more scalable but more wiring.
- Native-text vs. scanned PDFs — when Textract isn't wired, scanned
  PDFs produce no text_blocks. Should the producer fall back to OCR or
  return null and let the dashboard show a "PDF preview unavailable"
  message until OCR runs?

---

## P5 — B2B trust features *(starts after P3.c)*

Each item is small individually. Together they make the product
auditable, which is the gating concern for both AHJ procurement and
architect E&O carriers.

| Ticket | Scope | Effort | Status |
|---|---|---|---|
| **P5.a** | Per-finding audit trail export. PDF showing rule_id, code_ref, citation source+url, AI confidence, pipeline_version, generated_at, signature hash. Server-rendered, no JS. | 2–3 days | scoped |
| **P5.b** | Bluebeam Revu markup export. Export annotated PDF as Bluebeam Studio Markup format (`.bax` overlay) so reviewers can open in their existing tool. | 1–2 weeks | scoped |
| **P5.c** | Revit / DWG ingest pipeline. Stream model geometry → typed scope without going through PDF. Order-of-magnitude accuracy improvement on areas, occupant loads, fixture counts. | 3–6 months | deferred |

**Success metric:** A reviewer (AHJ) or principal (firm) can download a
single PDF for any finding that contains every piece of provenance an
E&O insurer or appeal hearing would ask for. Bluebeam export opens
correctly in Bluebeam Revu 21 on a stock install with no plug-ins.

**Open question:** Bluebeam's BAX format is proprietary and undocumented.
Alternative: standard PDF annotations (FreeText, Square) which Bluebeam
imports fine. Less polished but ships in 2 days instead of 2 weeks.
Default to standard PDF annotations unless a real customer asks for BAX.

---

## P2 — LADBS-specific knowledge layer *(starts after P3.d)*

The moat. Generic IBC knowledge is table stakes; LADBS knowledge is what
nobody else has. Built incrementally as a pipeline rather than a single
deliverable.

| Ticket | Scope | Effort | Status |
|---|---|---|---|
| **P2.a** | LADBS Information Bulletin scraper. Targets `ladbs.org/services/check-status-and-fees/forms-and-publications`. Pulls every IB / P-BC / Code Interpretation Bulletin into the corpus with `jurisdictionKey: "CA:LOS_ANGELES"`. | 1 week | scoped |
| **P2.b** | LADBS-overlay rule injection. New `LADBS_OVERLAY_RULES` array (HPOZ, Coastal, Q-conditions, Mello Act, soft-story, hillside, methane zone, Alquist-Priolo). Triage runner injects them when surveyor returns a LADBS jurisdiction key. Mirrors existing CALFIRE_WUI_RULES / CALGREEN_MANDATORY_RULES patterns. | 1–2 weeks | scoped |
| **P2.c** | ADU streamlining logic. Detect SB 9 / AB 1033 / state-bonus ADUs from scope, attach the correct LADBS form to the triage report, surface streamlining-eligibility findings. | 1 week | scoped |
| **P2.d** | Real LADBS correction-notice corpus. Partner with 3–5 firms, anonymize their last 50 LADBS correction notices each, build a probabilistic "what will this examiner cite" predictor on top of the rule engine. | 4–8 weeks + partner BD time | research |

**Success metric:** A LADBS submittal that the current engine scores
75/100 should score within 5 points of the score it would get after a
real reviewer's first-pass triage. Citations should reference the
correct LADBS IB number when one supersedes the base code.

**Open question:** Corpus licensing for LADBS bulletins. Bulletins are
public records but our ingest needs to confirm the scraper respects
robots.txt and rate limits. Worth a 30-min compliance review before
running at scale.

---

## P4 — LADBS bulletin diff newsletter *(parallel track, low blocking)*

Can ship in any window because it touches none of the core engine.

| Ticket | Scope | Effort | Status |
|---|---|---|---|
| **P4.a** | Daily cron that diffs LADBS bulletin pages, persists changes in a new `bulletin_changes` table, sends an email digest to subscribers via Resend (already a Vercel-native integration) or Supabase smtp. | 1 week | scoped |
| **P4.b** | Free public subscribe page at `/bulletin-digest`. Captures email → adds to newsletter. Top-of-funnel for both audiences. | 2 days | scoped |
| **P4.c** | Paid tier: full redline of each change, "what this means for your project" plain-English summary, archive search. | 1 week (post P4.a) | scoped |

**Success metric:** 200 free subscribers within 60 days of launch. 5%
paid conversion within 6 months.

**Open question:** Compliance / legal liability for paraphrasing LADBS
bulletins in a paid newsletter. Lift verbatim text + cite, don't
interpret. Pattern-match existing `docs/ICC_LICENSING.md` constraints.

---

## P1 — Pre-submittal mode (architect-side UX flip) *(after P3 + P5.a)*

The biggest single-audience deliverable. Same engine, fully different UX.
Don't start until P3 + P5.a are shipped because those are the foundation
features the demo depends on.

| Ticket | Scope | Effort | Status |
|---|---|---|---|
| **P1.a** | Single-tenant architect auth flow. New route `/check` outside the `(dashboard)` group; uses the same Supabase auth but a simpler onboarding (no agency setup, no role picker). | 1 week | scoped |
| **P1.b** | LADBS-styled correction-notice report format. Mirrors LADBS's actual notice layout: header block, applicant info, list of findings with examiner-style language, signature block. Exports as PDF. | 1–2 weeks | scoped |
| **P1.c** | "Submittal-ready" score widget. 0–100 with category breakdown (life safety, ADA, energy, structural, zoning). Becomes the top-of-page CTA. | 3–5 days | scoped |
| **P1.d** | Billing on the architect path. Stripe direct (not Vercel marketplace — that's for B2C). Per-seat pricing $300/seat/month or per-firm $2K/mo flat ≤10 architects. | 1–2 weeks | scoped |
| **P1.e** | Bulk-upload + project bundling. Architects work on multiple projects in parallel; one project should hold a planset across revisions. | 1 week | scoped |

**Success metric:** A first-time architect can sign up, upload a planset,
and receive a downloadable LADBS-styled correction-notice PDF in under
10 minutes from landing on the marketing site, without talking to sales.

**Open question:** Brand split — is the architect product called
"PhiCodes" or something different? Architects' procurement instinct is
different from cities'. Brand carries pricing perception.

---

## Cross-cutting concerns

These thread through everything above and don't fit a single ticket.

- **Eval harness expansion.** Every new rule (P2.b, P2.c, P5.a citation
  format changes) must clear `scripts/eval/run-eval.ts` with no per-
  archetype F1 drop > 2 pts. Hard NO per PILOT_BRIEF.
- **Doc updates.** As architect-side features land, update PILOT_BRIEF.md
  and ARCHITECTURE.md so the lock-language stops contradicting reality.
  Currently both say "this is the building inspector's tool" — that
  language was overridden 2026-06-02 but the files still say it.
- **Pricing decision.** P1.d ships with a fixed price, but the
  "$15K–25K/yr per city" AHJ pricing in PILOT_BRIEF is also up for
  review now that we're running two products. Worth a single decision
  rather than two drift independently.
- **Telemetry.** Every demo moment needs to be measured. How long to
  first useful finding? How many click-to-page interactions per
  session? How many findings does the reviewer mark "wrong"? Without
  these we're guessing at PMF.

---

## What's not on this list

- N-of-5 critic ensembles, multi-vote LLM panels — Hard NO per brief
- Title 24 prescriptive energy compliance checker — Hard NO per brief
- Reviewer dashboard rewrite in a different framework — Hard NO per brief
- General-purpose AEC tools (energy modeling, rendering, BIM coord) —
  out of scope for both audiences; depth in plan review beats breadth
- TikTok / Instagram marketing — wrong demographic per prior analysis
- General Google Ads on "permit help" — too noisy, low intent

---

## Current execution state

- **P3.a** is the next ticket starting now (2026-06-02 session).
- **P3.b, P3.c** follow this session if scope permits.
- **P5.a** scoped, follows P3 completion.
- Everything else is documented and scheduled, not yet started.

Tickets are tracked in this session's task list (TaskList tool). When a
ticket completes, mark the row "shipped" and link the commit hash here.
