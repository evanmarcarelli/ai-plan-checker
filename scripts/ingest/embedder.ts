// =====================================================================
// Embedder — batch embedding generation via OpenAI API.
//
// Model: text-embedding-3-small (1536 dims)
//   Cost: $0.020 / 1M tokens
//   Full corpus (~1,740 chunks × ~500 tokens): ~870K tokens = ~$0.017
//
// Batching: OpenAI allows up to 2,048 inputs per request with a 300K
// token cap per batch. We use batches of 96 inputs (~48K tokens) to
// stay well within limits and enable clean retry logic.
//
// Rate limit: text-embedding-3-small tier is 3,000 RPM / 1M TPM.
// At 96 inputs × ~500 tokens, we need ~18 batches for the full corpus.
// Each batch costs ~1 RPM. Well within limits even with retries.
// =====================================================================

const OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings";
const EMBED_MODEL = "text-embedding-3-small";
const BATCH_SIZE = 96;
const MAX_RETRIES = 3;
const RETRY_DELAY_BASE_MS = 1000;

export interface EmbedResult {
  text: string;
  embedding: number[];
  tokenCount: number;
}

// =====================================================================
// Embed a single text string
// =====================================================================
export async function embedOne(text: string, apiKey: string): Promise<number[]> {
  const results = await embedBatch([text], apiKey);
  return results[0].embedding;
}

// =====================================================================
// Embed a batch of texts (up to BATCH_SIZE per call)
// Returns results in the same order as the input.
// =====================================================================
export async function embedBatch(
  texts: string[],
  apiKey: string,
): Promise<EmbedResult[]> {
  if (texts.length === 0) return [];

  // Trim each text to 8191 tokens (OpenAI hard limit)
  const trimmed = texts.map(t => t.slice(0, 32_000));  // ~8K tokens

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const r = await fetch(OPENAI_EMBED_URL, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: EMBED_MODEL,
          input: trimmed,
          encoding_format: "float",
        }),
      });

      if (r.status === 429 || r.status >= 500) {
        const retryAfter = parseInt(r.headers.get("retry-after") ?? "0", 10);
        const wait = retryAfter > 0
          ? retryAfter * 1000
          : RETRY_DELAY_BASE_MS * Math.pow(2, attempt - 1);
        console.warn(`  [embed] HTTP ${r.status}, retry ${attempt}/${MAX_RETRIES} in ${wait}ms`);
        await sleep(wait);
        continue;
      }

      if (!r.ok) {
        const txt = await r.text().catch(() => "");
        throw new Error(`OpenAI embed ${r.status}: ${txt.slice(0, 300)}`);
      }

      const j = await r.json();
      const data = (j.data ?? []) as Array<{ index: number; embedding: number[] }>;
      const usage = j.usage ?? {};

      // Map back in input order
      const results: EmbedResult[] = texts.map((text, i) => {
        const hit = data.find(d => d.index === i);
        return {
          text,
          embedding: hit?.embedding ?? [],
          tokenCount: Math.ceil((usage.total_tokens ?? 0) / texts.length),
        };
      });

      return results;

    } catch (err) {
      if (attempt === MAX_RETRIES) throw err;
      const wait = RETRY_DELAY_BASE_MS * Math.pow(2, attempt - 1);
      console.warn(`  [embed] error attempt ${attempt}: ${(err as Error).message}, retry in ${wait}ms`);
      await sleep(wait);
    }
  }

  throw new Error("embedBatch exhausted retries");
}

// =====================================================================
// Embed a large array of texts in safe batches with progress reporting
// =====================================================================
export async function* embedAll(
  texts: string[],
  apiKey: string,
  batchSize = BATCH_SIZE,
): AsyncGenerator<{ results: EmbedResult[]; batchIndex: number; totalBatches: number }> {
  const totalBatches = Math.ceil(texts.length / batchSize);

  for (let i = 0; i < texts.length; i += batchSize) {
    const batch = texts.slice(i, i + batchSize);
    const batchIndex = Math.floor(i / batchSize) + 1;

    console.log(`  [embed] batch ${batchIndex}/${totalBatches} (${batch.length} texts)`);

    const results = await embedBatch(batch, apiKey);
    yield { results, batchIndex, totalBatches };

    // Brief cooldown between batches to be a polite API citizen
    if (i + batchSize < texts.length) {
      await sleep(200);
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms));
}
