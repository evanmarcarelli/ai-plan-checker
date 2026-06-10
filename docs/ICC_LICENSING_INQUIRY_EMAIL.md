# ICC Digital Codes — Licensing Inquiry Email

Send to: `licensinginfo@iccsafe.org` (cc `digitalcodes@iccsafe.org` if your account manager is known)

Subject options (pick one):
- `Architechtura — Digital Content License inquiry (IBC 2024 + I-Code suite)`
- `Licensing inquiry: programmatic IBC/IRC/IECC access for AI plan-check SaaS`

---

## Draft

> Hello ICC Licensing Team,
>
> I'm the founder of **Architechtura**, an AI plan-checking platform that automates building-code and zoning compliance review for design teams and AHJs. We're at the stage where we need licensed, programmatic access to the 2024 I-Codes — and we'd rather build the partnership cleanly from day one than work around it.
>
> **What we need access to**
>
> - 2024 IBC, IRC, IECC, IFC, IPC, IMC, IFGC, IEBC, IPMC, ISPSC, IWUIC, IGCC, IZC (full text, structured if available)
> - Section-level metadata: hierarchy, parent/child references, tables, figures
> - Programmatic retrieval — REST API or bulk export with reasonable refresh cadence
> - Permission to display **cited section text** in-product to the licensed end user (plan reviewer / design professional running a project)
>
> **How we'd use it**
>
> Our system retrieves relevant code sections during plan review and surfaces them to the reviewer with verbatim text and citation. Text is shown to **the licensed end user only** — it is not redistributed, syndicated, or exposed via a public API. Every quote is bounded to the cited section's scope.
>
> **What we'd want to discuss on a call**
>
> 1. Tier and pricing for a startup-stage commercial SaaS (likely the Digital Content License tier — happy to share projected query volume)
> 2. Whether bulk text + structured metadata are licensable together, or only via API
> 3. Update cadence and how new editions (2027 cycle) flow through the license
> 4. Whether jurisdictional amendments published by states/municipalities are in-scope, or whether those are handled separately
> 5. Any case studies of similar AI/plan-review partners — we'd love to learn from how other licensees structured their integration
>
> **About us, briefly**
>
> Architechtura is built in California and is currently piloting with [N] design firms across LA County and the Pacific Northwest. We treat code accuracy as a product-defining problem, which is why we're approaching licensing now rather than scraping public previews. Happy to send a short product walkthrough if useful.
>
> A 20-minute intro call would be ideal. What's your preferred next step?
>
> Best,
> **Evan Marcarelli**
> Founder, Architechtura
> [phone]
> [website]
> [calendar link]

---

## Notes for the sender

- **Lead with the partnership frame, not the pricing question.** ICC's licensing team has a real interest in legitimate AI partners — being one of the first signing properly is leverage you can use on price.
- **Don't reveal you've considered scraping.** Don't reference UpCodes either; let them position vs. competitors themselves.
- **Concrete pilot numbers (firms, query volume projection) move the conversation faster than abstract "early-stage SaaS."** If you don't have hard numbers yet, leave the pilot count vague rather than inventing one.
- **Expect the first response to be a sales-qualification form, not pricing.** They'll route you to a content-licensing rep based on use case.
- **Likely deal size:** $5K–$25K/yr for a startup tier per `ICC_LICENSING.md`. Don't anchor first — let them propose.
- **Things they'll ask:** projected MAUs, whether you display full sections or excerpts, whether the product is end-user-facing or AHJ-facing, geographic scope, redistribution model.

## Fallback if they're slow

If no response in 10 business days, follow up once with a one-sentence bump. If still nothing, the practical near-term path is the **UpCodes API** (`up.codes/api-docs`) — they've already pre-licensed IBC + state codes and resell programmatic access, which gets you to verbatim text without an ICC contract.
