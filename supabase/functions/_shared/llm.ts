// =====================================================================
// Shared LLM client.
//
// Wraps Anthropic (primary) and OpenAI (fallback) with:
//   - Structured-output enforcement (caller provides a JSON schema; we
//     keep retrying until the model returns matching JSON or we give up)
//   - Per-call cost tracking written to the llm_usage table
//   - Exponential backoff on transient failures
//   - Hard timeout — never hang the pipeline waiting on a slow LLM
// =====================================================================
import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.0";

// ---------------------------------------------------------------------
// Pricing (USD per 1M tokens). Update these as model prices change.
// Source of truth = your provider dashboard.
// ---------------------------------------------------------------------
const PRICING: Record<string, { input: number; output: number }> = {
  "claude-opus-4-7":          { input: 15.0, output: 75.0 },
  "claude-sonnet-4-6":        { input: 3.0,  output: 15.0 },
  "claude-haiku-4-5-20251001":{ input: 1.0,  output: 5.0  },
  "gpt-4o":                   { input: 2.5,  output: 10.0 },
  "gpt-4o-mini":              { input: 0.15, output: 0.60 },
};

export interface LlmCallContext {
  agencyId?: string;
  submittalId?: string;
  triageRunId?: string;
  purpose: string;          // 'extract_scope' | 'draft_comment' | 'triage_judgment' | etc.
}

export interface StructuredCallParams<T> {
  // One of these two — pick the model tier appropriate to the task.
  model?: string;            // overrides default
  tier?: "fast" | "balanced" | "deep";
  // System prompt (instructions about role + output shape)
  system: string;
  // User message
  user: string;
  // Optional pre-baked example exchanges (few-shot)
  examples?: Array<{ user: string; assistant: string }>;
  // JSON schema the response MUST match (we coerce + validate)
  schema: object;
  // Fallback default if the LLM totally fails after retries
  fallback?: T;
  // Max retries for transient errors
  maxRetries?: number;
  // Hard timeout in ms (default 60s)
  timeoutMs?: number;
}

// =====================================================================
// Tool-use API (used by the Researcher agent)
// =====================================================================
export interface ToolDef {
  name: string;
  description: string;
  input_schema: { type: "object"; properties: Record<string, unknown>; required?: string[] };
}

export interface ToolCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResult {
  tool_use_id: string;
  content: string;
  is_error?: boolean;
}

export interface ToolLoopParams<T> {
  model?: string;
  tier?: "fast" | "balanced" | "deep";
  system: string;
  initialUser: string;
  tools: ToolDef[];
  executeTool: (call: ToolCall) => Promise<ToolResult>;
  maxIterations?: number;
  timeoutMs?: number;
  parseFinal: (text: string) => T;
}

export interface ToolLoopResult<T> {
  final: T | null;
  iterations: number;
  toolCalls: number;
  raw: string;
}

const DEFAULT_MODELS: Record<"fast" | "balanced" | "deep", string> = {
  fast:     "claude-haiku-4-5-20251001",
  balanced: "claude-sonnet-4-6",
  deep:     "claude-opus-4-7",
};

export class LlmClient {
  private anthropicKey: string;
  private openaiKey: string;
  private supabase: SupabaseClient;

  constructor(anthropicKey: string, openaiKey: string, supabase: SupabaseClient) {
    this.anthropicKey = anthropicKey;
    this.openaiKey = openaiKey;
    this.supabase = supabase;
  }

  /**
   * Call an LLM expecting a JSON response that matches `schema`.
   * Returns the parsed object, or throws after exhausting retries
   * unless `fallback` is provided.
   */
  async structured<T>(ctx: LlmCallContext, params: StructuredCallParams<T>): Promise<T> {
    const model = params.model ?? DEFAULT_MODELS[params.tier ?? "balanced"];
    const maxRetries = params.maxRetries ?? 2;
    const timeoutMs = params.timeoutMs ?? 60_000;

    let lastErr: Error | null = null;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        const result = await this._callOnce<T>(ctx, params, model, timeoutMs, attempt);
        return result;
      } catch (err) {
        lastErr = err as Error;
        // Exponential backoff for transient errors
        const isRetryable =
          /^(429|5\d\d|timeout|network|fetch)/i.test(lastErr.message);
        if (!isRetryable || attempt === maxRetries) break;
        const wait = Math.min(1000 * Math.pow(2, attempt), 8000) + Math.random() * 500;
        await new Promise(r => setTimeout(r, wait));
      }
    }

    if (params.fallback !== undefined) {
      console.warn(`LLM call failed (purpose=${ctx.purpose}); using fallback. Last error:`, lastErr);
      return params.fallback;
    }
    throw lastErr ?? new Error("LLM call failed");
  }

  // -------------------------------------------------------------------
  private async _callOnce<T>(
    ctx: LlmCallContext,
    params: StructuredCallParams<T>,
    model: string,
    timeoutMs: number,
    attempt: number,
  ): Promise<T> {
    const useAnthropic = model.startsWith("claude-");
    const t0 = Date.now();
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort("timeout"), timeoutMs);

    let raw: string;
    let inputTokens = 0;
    let outputTokens = 0;
    try {
      if (useAnthropic) {
        ({ raw, inputTokens, outputTokens } = await callAnthropic(
          this.anthropicKey, model, params, ac.signal,
        ));
      } else {
        ({ raw, inputTokens, outputTokens } = await callOpenAI(
          this.openaiKey, model, params, ac.signal,
        ));
      }
    } finally {
      clearTimeout(timer);
    }

    const latency = Date.now() - t0;
    const cost = this._cost(model, inputTokens, outputTokens);

    // Log usage (best-effort — don't block on failures)
    this.supabase.from("llm_usage").insert({
      agency_id: ctx.agencyId ?? null,
      submittal_id: ctx.submittalId ?? null,
      triage_run_id: ctx.triageRunId ?? null,
      provider: useAnthropic ? "anthropic" : "openai",
      model,
      purpose: ctx.purpose,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      cost_usd: cost,
      latency_ms: latency,
    }).then(({ error }) => {
      if (error) console.warn("llm_usage log failed:", error.message);
    });

    // Parse + validate JSON
    const parsed = this._parseJson<T>(raw, params.schema, attempt);
    return parsed;
  }

  private _cost(model: string, inputTokens: number, outputTokens: number): number {
    const p = PRICING[model];
    if (!p) return 0;
    return (inputTokens * p.input + outputTokens * p.output) / 1_000_000;
  }

  private _parseJson<T>(raw: string, _schema: object, _attempt: number): T {
    // Strip ```json fences if the model added them
    let s = raw.trim();
    s = s.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
    // Some models prefix with prose before the JSON — find first { or [
    const start = s.search(/[\{\[]/);
    if (start > 0) s = s.slice(start);
    // Trim trailing prose after the last } or ]
    let end = -1;
    let depth = 0;
    let inStr = false;
    let esc = false;
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (esc) { esc = false; continue; }
      if (c === "\\") { esc = true; continue; }
      if (c === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (c === "{" || c === "[") depth++;
      if (c === "}" || c === "]") { depth--; if (depth === 0) end = i + 1; }
    }
    if (end > 0) s = s.slice(0, end);

    try {
      return JSON.parse(s) as T;
    } catch (err) {
      throw new Error(`LLM returned non-JSON: ${(err as Error).message}. Got: ${s.slice(0, 200)}`);
    }
  }

  // ===================================================================
  // Tool-use loop (Anthropic only — OpenAI fallback not implemented for
  // tool-use because the tool_use API surface differs significantly).
  //
  // Loops the model until it emits a final text response without any
  // tool_use blocks, or maxIterations is reached.
  // ===================================================================
  async runToolLoop<T>(ctx: LlmCallContext, params: ToolLoopParams<T>): Promise<ToolLoopResult<T>> {
    const model = params.model ?? DEFAULT_MODELS[params.tier ?? "balanced"];
    const maxIterations = params.maxIterations ?? 6;
    const timeoutMs = params.timeoutMs ?? 120_000;

    type Msg =
      | { role: "user" | "assistant"; content: string }
      | { role: "user" | "assistant"; content: Array<Record<string, unknown>> };

    const messages: Msg[] = [
      { role: "user", content: params.initialUser },
    ];

    let iterations = 0;
    let toolCalls = 0;
    let lastText = "";
    const t0 = Date.now();

    while (iterations < maxIterations) {
      if (Date.now() - t0 > timeoutMs) {
        console.warn(`tool-loop timeout after ${iterations} iterations`);
        break;
      }
      iterations++;

      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort("timeout"), 60_000);

      let response: { content: Array<Record<string, unknown>>; stop_reason: string; usage: { input_tokens: number; output_tokens: number } };
      try {
        const r = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          signal: ac.signal,
          headers: {
            "Content-Type": "application/json",
            "x-api-key": this.anthropicKey,
            "anthropic-version": "2023-06-01",
          },
          body: JSON.stringify({
            model,
            max_tokens: 4000,
            system: params.system,
            tools: params.tools,
            messages,
          }),
        });
        if (!r.ok) {
          const txt = await r.text().catch(() => "");
          throw new Error(`tool-loop ${r.status}: ${txt.slice(0, 300)}`);
        }
        response = await r.json();
      } finally {
        clearTimeout(timer);
      }

      // Cost log (best-effort)
      const cost = this._cost(model, response.usage?.input_tokens ?? 0, response.usage?.output_tokens ?? 0);
      this.supabase.from("llm_usage").insert({
        agency_id: ctx.agencyId ?? null,
        submittal_id: ctx.submittalId ?? null,
        triage_run_id: ctx.triageRunId ?? null,
        provider: "anthropic",
        model,
        purpose: ctx.purpose + ":tool_loop",
        input_tokens: response.usage?.input_tokens ?? 0,
        output_tokens: response.usage?.output_tokens ?? 0,
        cost_usd: cost,
        latency_ms: Date.now() - t0,
      }).then(({ error }) => { if (error) console.warn("llm_usage log failed:", error.message); });

      // Did the assistant request tool calls?
      const toolUses = (response.content ?? []).filter((b) => b["type"] === "tool_use") as Array<{ id: string; name: string; input: Record<string, unknown> }>;
      const textBlocks = (response.content ?? []).filter((b) => b["type"] === "text") as Array<{ text: string }>;
      lastText = textBlocks.map((b) => b.text).join("\n");

      // Append the assistant's response to message history
      messages.push({
        role: "assistant",
        content: response.content as Array<Record<string, unknown>>,
      });

      if (toolUses.length === 0 || response.stop_reason === "end_turn") {
        // Final answer reached
        break;
      }

      // Execute the tool calls and append results
      const resultsBlock: Array<Record<string, unknown>> = [];
      for (const tu of toolUses) {
        toolCalls++;
        try {
          const result = await params.executeTool({ id: tu.id, name: tu.name, input: tu.input });
          resultsBlock.push({
            type: "tool_result",
            tool_use_id: result.tool_use_id,
            content: result.content,
            is_error: result.is_error ?? false,
          });
        } catch (err) {
          resultsBlock.push({
            type: "tool_result",
            tool_use_id: tu.id,
            content: `error: ${(err as Error).message}`,
            is_error: true,
          });
        }
      }
      messages.push({ role: "user", content: resultsBlock });
    }

    let final: T | null = null;
    if (lastText) {
      try { final = params.parseFinal(lastText); }
      catch (err) { console.warn("parseFinal failed:", err); }
    }

    return { final, iterations, toolCalls, raw: lastText };
  }
}

// ---------------------------------------------------------------------
// Anthropic API caller
// ---------------------------------------------------------------------
async function callAnthropic(
  apiKey: string,
  model: string,
  params: StructuredCallParams<unknown>,
  signal: AbortSignal,
): Promise<{ raw: string; inputTokens: number; outputTokens: number }> {

  const messages: Array<{ role: "user" | "assistant"; content: string }> = [];
  if (params.examples) {
    for (const ex of params.examples) {
      messages.push({ role: "user",      content: ex.user });
      messages.push({ role: "assistant", content: ex.assistant });
    }
  }
  // Append "respond ONLY with JSON" reinforcement to the user message
  const userMsg = params.user + "\n\nRespond with ONLY a JSON object that matches the requested schema. No prose, no code fences, no commentary.";
  messages.push({ role: "user", content: userMsg });

  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model,
      max_tokens: 4000,
      system: params.system + "\n\nYou must respond with valid JSON only — no prose, no markdown fences.",
      messages,
    }),
  });

  if (!r.ok) {
    const txt = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${txt.slice(0, 300)}`);
  }
  const j = await r.json();
  const raw = (j.content?.[0]?.text ?? "") as string;
  return {
    raw,
    inputTokens: j.usage?.input_tokens ?? 0,
    outputTokens: j.usage?.output_tokens ?? 0,
  };
}

// ---------------------------------------------------------------------
// OpenAI API caller (fallback)
// ---------------------------------------------------------------------
async function callOpenAI(
  apiKey: string,
  model: string,
  params: StructuredCallParams<unknown>,
  signal: AbortSignal,
): Promise<{ raw: string; inputTokens: number; outputTokens: number }> {

  const messages: Array<{ role: "system" | "user" | "assistant"; content: string }> = [
    { role: "system", content: params.system },
  ];
  if (params.examples) {
    for (const ex of params.examples) {
      messages.push({ role: "user",      content: ex.user });
      messages.push({ role: "assistant", content: ex.assistant });
    }
  }
  messages.push({ role: "user", content: params.user });

  const r = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages,
      response_format: { type: "json_object" },
      temperature: 0.1,
    }),
  });

  if (!r.ok) {
    const txt = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${txt.slice(0, 300)}`);
  }
  const j = await r.json();
  const raw = (j.choices?.[0]?.message?.content ?? "") as string;
  return {
    raw,
    inputTokens: j.usage?.prompt_tokens ?? 0,
    outputTokens: j.usage?.completion_tokens ?? 0,
  };
}

// ---------------------------------------------------------------------
// Factory used by edge functions
// ---------------------------------------------------------------------
export function makeLlmClient(): LlmClient {
  const sb = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );
  return new LlmClient(
    Deno.env.get("ANTHROPIC_API_KEY") ?? "",
    Deno.env.get("OPENAI_API_KEY") ?? "",
    sb,
  );
}
