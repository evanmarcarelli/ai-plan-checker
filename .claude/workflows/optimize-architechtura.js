export const meta = {
  name: 'optimize-architechtura',
  description: 'Scout the whole codebase in parallel (one agent per development department) against a real measured baseline, and return a ranked optimization backlog. Read-only: it proposes, it does not merge. Feed a backlog item to /optimize to execute it with a real before/after gate.',
  whenToUse: 'When you want a prioritized, baseline-grounded list of where to spend optimization effort across every sector (deterministic rules, corpus, eval signal, architecture/cost, LLM reviewers) at once.',
  phases: [
    { title: 'Baseline', detail: 'measure current accuracy with the free local harnesses' },
    { title: 'Scout', detail: 'one department agent per sector finds its top opportunities (read-only)' },
    { title: 'Rank', detail: 'merge + rank into one backlog (free-local + high-impact first)' },
  ],
}

// The departments mirror the product's plan-check departments. `free` = its
// optimization loop closes locally with no API key (so it ranks first).
const DEPARTMENTS = [
  { type: 'deterministic-rules', focus: 'explicit numeric checks AND interpreted->deterministic promotions (raise precision + cut cost together)', free: true },
  { type: 'corpus-ingest',       focus: 'jurisdiction coverage gaps and the DGS amendment backlog', free: true },
  { type: 'eval-engineer',       focus: 'eval-signal coverage (archetypes under 10 observations) and citation validity', free: true },
  { type: 'architect',           focus: 'pipeline cost/latency, the department routing pre-screen, config tunables', free: true },
  { type: 'reviewer-tuning',     focus: 'LLM reviewer prompts, model tiering, and critic behavior', free: false },
]

const BASELINE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['det_f1', 'archetype_gate', 'citation_validity', 'summary'],
  properties: {
    det_f1: { type: ['number', 'null'], description: 'OVERALL F1 from run_eval, or null if it errored' },
    archetype_gate: { type: ['number', 'null'], description: 'archetype-gate fraction (target 0.95), or null' },
    citation_validity: { type: ['number', 'null'], description: 'from `python -m benchmarks` dry, or null' },
    summary: { type: 'string', description: 'one paragraph: the numbers + any harness errors' },
  },
}

const OPP_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['department', 'opportunities'],
  properties: {
    department: { type: 'string' },
    opportunities: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['title', 'change', 'gate', 'metric', 'expected_direction', 'effort', 'free_local', 'impact', 'rationale'],
        properties: {
          title: { type: 'string' },
          change: { type: 'string', description: 'the concrete change, naming real files' },
          gate: { type: 'string', description: 'run_eval | benchmarks-dry | benchmarks-live | corpus-load | pytest' },
          metric: { type: 'string', description: 'det_f1 | citation_validity | critical_recall | cost | latency | coverage' },
          expected_direction: { type: 'string', enum: ['up', 'down'] },
          effort: { type: 'string', enum: ['S', 'M', 'L'] },
          free_local: { type: 'boolean', description: 'true if the gate closes locally with no API key' },
          impact: { type: 'string', enum: ['high', 'medium', 'low'] },
          rationale: { type: 'string' },
        },
      },
    },
  },
}

const goal = (args && args.goal) || 'maximize accuracy and efficiency across every sector; prefer changes whose gate runs free and local'
const depList = (args && Array.isArray(args.departments) && args.departments.length)
  ? DEPARTMENTS.filter(d => args.departments.includes(d.type))
  : DEPARTMENTS

// ── Phase 1: real measured baseline (read-only) ──────────────────────────────
phase('Baseline')
const baseline = await agent(
  `You are scouting the CURRENT measured baseline for Architechtura. Do NOT edit any files.
Run the two FREE local harnesses and report the numbers:
- From backend/:  python -m scripts.eval.run_eval     -> OVERALL F1 (det_f1) and the archetype-gate fraction.
- From repo root: python -m benchmarks                -> Citation Validity.
If a harness errors (missing dep, no API key, import error), set that field to null and explain in summary. Report numbers, not vibes.`,
  { schema: BASELINE_SCHEMA, agentType: 'eval-engineer', phase: 'Baseline', label: 'baseline' },
)

log(`Baseline — det_f1=${baseline ? baseline.det_f1 : '?'} gate=${baseline ? baseline.archetype_gate : '?'} citation=${baseline ? baseline.citation_validity : '?'}`)
const baselineSummary = baseline ? baseline.summary : 'baseline unavailable'

// ── Phase 2: parallel department scouts (read-only) ──────────────────────────
// Barrier (parallel) is correct here: ranking needs every department's list at once.
phase('Scout')
const scouted = await parallel(depList.map(d => () => agent(
  `You are the ${d.type} department running a READ-ONLY scouting pass. Do NOT edit any files — only read code and report opportunities.

Optimization goal: ${goal}
Your focus: ${d.focus}
Current measured baseline: ${baselineSummary}

Identify your 1-4 highest-ROI optimization opportunities. For each, name the concrete change (real file paths), which gate would MEASURE it (${d.free ? 'a free local gate exists for your track' : 'your precision gate needs an API key + budget'}), the metric and direction, rough effort (S/M/L), whether the loop closes locally for free, the impact (high/medium/low), and a one-line rationale. Be specific and honest — if your best idea needs a paid run to verify, say so. Prefer interpreted->deterministic promotions where they apply.`,
  { schema: OPP_SCHEMA, agentType: d.type, phase: 'Scout', label: `scout:${d.type}` },
)))

// ── Phase 3: merge + rank (plain JS, no agents) ──────────────────────────────
phase('Rank')
const IMPACT = { high: 3, medium: 2, low: 1 }
const EFFORT = { S: 1, M: 2, L: 3 }

const backlog = scouted
  .filter(Boolean)
  .flatMap(r => (r.opportunities || []).map(o => ({ ...o, department: r.department })))
  .sort((a, b) =>
    (b.free_local === a.free_local ? 0 : b.free_local ? 1 : -1) ||           // free-local first
    ((IMPACT[b.impact] || 0) - (IMPACT[a.impact] || 0)) ||                    // then impact
    ((EFFORT[a.effort] || 9) - (EFFORT[b.effort] || 9))                      // then least effort
  )

const free = backlog.filter(o => o.free_local).length
log(`Backlog: ${backlog.length} opportunities (${free} free-local). Top: ${backlog.slice(0, 3).map(o => o.title).join(' | ')}`)

// Returned to the caller for review. Nothing was changed. To execute an item,
// run:  /optimize "<title or change>"  — which implements + gates + asks approval.
return {
  goal,
  baseline,
  backlog,
  note: 'Read-only scout. No files changed. Feed any backlog item to /optimize to execute it with a real before/after gate (propose -> approve).',
}
