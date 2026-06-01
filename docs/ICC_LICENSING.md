# ICC Licensing Decision — IBC Verbatim Text

## Decision

**Version 1: Cite + summarize; do not quote IBC verbatim.**

The International Building Code (IBC) is copyrighted by the International Code Council (ICC). Reproducing extended verbatim passages in a commercial SaaS product without a paid license is a copyright infringement risk.

Until an ICC API/digital license is in place, the researcher agent:
- Cites the IBC section number precisely (e.g., "IBC 1006.3.2")
- Provides a plain-language summary of what the section requires
- Quotes ≤ 200 characters of IBC text when it appears on a legally-hosted source (fair-use margin)
- **Never** reproduces full section text from IBC verbatim

This restriction is enforced via the `RESEARCHER_SYSTEM` prompt in `_shared/research.ts`.

---

## What ICC licenses look like

| Tier | Product | Price (est.) | Use case |
|------|---------|--------------|----------|
| Single code PDF | IBC 2021 download | ~$150 | Internal reference only |
| Online access | cdpAccess subscription | ~$500/yr per user | Internal reviewer read access |
| Digital content license | API / embedded text | ~$5K–25K/yr | Programmatic use, display in SaaS |
| Enterprise OEM | Full verbatim integration | Custom (>$50K) | Embed IBC text in a product sold to others |

The relevant tier for Plan Room AHJ is the **Digital Content License** (~$5K–$25K/yr depending on volume). Ballpark is negotiated directly with ICC's licensing team.

**Contact:** [licensinginfo@iccsafe.org](mailto:licensinginfo@iccsafe.org)

---

## Alternatives to an ICC license

### 1. UpCodes API (recommended for v1.5)

UpCodes (upcodes.com) has licensed IBC and CBC text and exposes a search/lookup API. Subscribers can query code sections programmatically and display text within their product. UpCodes handles the ICC sublicense.

- Pricing: starts ~$200/mo for API access
- Covers: IBC, CBC, NYSBC, WSBC, FBC, and many other state/local codes
- API docs: https://up.codes/api-docs

This is the recommended integration path for Plan Room AHJ v1.5. It gives verbatim IBC + state code text without needing a direct ICC relationship.

### 2. State-adopted codes (public domain where applicable)

Many states publish their adopted building code amendments as public records, which are not subject to ICC copyright:
- California: Title 24 Parts are published by DSA and are free to access/quote
- New York: NYSBC is published as a free government document
- Washington: WSBC chapters are freely available from L&I

For CA-specific queries, the researcher can quote CBC (Title 24) verbatim since that's a state-published document, even though it's based on IBC.

### 3. upcodes.com + fair use for short excerpts

Citing the section number + a ≤ 200 character excerpt from a publicly-accessible hosted source (upcodes.com, iccsafe.org's free previews) is a defensible fair-use position for the purposes of building plan review commentary. This is the current approach for v1.

---

## Implementation checklist

- [x] Researcher system prompt updated to note ICC copyright restriction
- [x] Researcher defaults to ≤ 200 char IBC quotes when quoting from hosted sources
- [x] State codes (CBC, WSBC, etc.) exempt from restriction — researcher can quote freely
- [ ] UpCodes API integration (target: v1.5 / after first 3 paid contracts)
- [ ] Evaluate ICC Digital Content License if AHJ clients require full verbatim text in comment letters (unlikely — reviewers paraphrase anyway)

---

## Risk assessment

**Current risk (cite + summarize):** Low. Plan review comment letters do not typically quote IBC verbatim — reviewers cite section numbers and paraphrase. This is standard industry practice. No plan-check software tool currently licenses IBC for verbatim display.

**Risk if we quoted IBC verbatim without a license:** Moderate. ICC has sent cease-and-desist notices to third-party publishers. A commercial SaaS displaying IBC text is a clear target. The UpCodes API path resolves this cleanly.
