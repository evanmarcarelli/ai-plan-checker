// =====================================================================
// Text chunker for building code sections.
//
// Building codes are naturally structured into sections (e.g. CBC 701A.1).
// Our chunking strategy: one chunk per section, with 200-char context
// overlap from the previous section for cross-reference continuity.
//
// Input: the readable text extracted from a code section page
//        (after HTML stripping by fetchReadable()).
// Output: one or more CodeChunk objects ready for embedding.
//
// Why section-based over fixed-size chunking:
//   - Code citations are always at the section level
//   - Semantic search queries are section-level ("what does 701A.1 say")
//   - Splitting within a section loses the atomic unit of authority
//   - The IVFFlat index performs better with semantically complete chunks
// =====================================================================

export interface CodeChunk {
  // Identity (matches code_chunks schema)
  corpus_key: string;
  jurisdiction_key: string;
  code_name: string;
  part: string | null;
  chapter: string | null;
  chapter_title: string | null;
  section_ref: string | null;
  section_title: string | null;
  subsection: string | null;
  // Content
  chunk_text: string;
  token_count: number;   // estimated (chars / 4)
  source_url: string | null;
  code_year: string;
  // Content hash for deduplication on re-runs
  content_hash: string;
}

// =====================================================================
// Section reference patterns — ordered most-specific first
// =====================================================================
const SECTION_REF_PATTERNS: RegExp[] = [
  // CBC/CRC/CMC/CPC/CEC section: "CBC 701A.1.2.3" or "Section 701A.1"
  /\b(?:section\s+)?(\d{1,4}[A-Z]?(?:\.\d+){0,4})\b/i,
  // NEC article: "Article 230" or "230.95"
  /\bArticle\s+(\d{2,3}(?:\.\d+)?)\b/i,
  // Title 24 Part 6 section: "§ 130.0" or "Section 130.0(a)"
  /§\s*(\d{1,3}\.\d+(?:\([a-z]\))?)/i,
];

const SECTION_HEADER_RE = /^(?:SECTION\s+)?(\d{1,4}[A-Z]?\d*(?:\.\d+)*)\s+(.+)$/im;
const CHAPTER_HEADER_RE = /^CHAPTER\s+(\d+[A-Z]?)\s+(.+)$/im;

// Approximate token count (GPT-style: ~4 chars per token)
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

// =====================================================================
// Simple hash (FNV-1a style) for content deduplication
// =====================================================================
export function hashText(s: string): string {
  let h = 2166136261;
  for (let i = 0; i < Math.min(s.length, 4096); i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

// =====================================================================
// Parse a section reference from the first line of a chunk
// =====================================================================
export function parseSectionRef(text: string): { ref: string | null; title: string | null } {
  const firstLine = text.split("\n")[0].trim();
  const m = SECTION_HEADER_RE.exec(firstLine);
  if (m) return { ref: m[1], title: m[2].trim() };

  for (const re of SECTION_REF_PATTERNS) {
    const m2 = re.exec(firstLine);
    if (m2) return { ref: m2[1], title: null };
  }

  return { ref: null, title: null };
}

// =====================================================================
// Split a full document page into section chunks.
//
// Strategy:
//  1. Look for section header lines ("701A.1 SCOPE" or "SECTION 701A.1")
//  2. Each header starts a new chunk
//  3. If no section headers found: treat the whole page as one chunk
//  4. Chunks larger than MAX_CHARS are split at paragraph boundaries
// =====================================================================
const MAX_CHARS = 3000;   // ~750 tokens — comfortable context window slice
const MIN_CHARS = 80;     // skip trivially short fragments

export function chunkDocument(
  fullText: string,
  meta: {
    corpusKey: string;
    jurisdictionKey: string;
    codeName: string;
    part: string | null;
    chapter: string | null;
    chapterTitle: string | null;
    sourceUrl: string | null;
    codeYear: string;
  },
): CodeChunk[] {
  if (!fullText?.trim()) return [];

  // Split on section headers: lines that look like "701A.1 Title" or "SECTION 701A.1"
  const sectionSplitRe = /(?=^(?:SECTION\s+)?\d{1,4}[A-Z]?\d*(?:\.\d+)*\s+\S)/im;
  const rawSections = fullText.split(sectionSplitRe).filter(s => s.trim().length > MIN_CHARS);

  // If splitting produced nothing useful, treat the whole page as one chunk
  const sections = rawSections.length > 1 ? rawSections : [fullText];

  const chunks: CodeChunk[] = [];
  let prevTail = "";  // 200-char tail of previous section for overlap context

  for (let i = 0; i < sections.length; i++) {
    const raw = sections[i].trim();
    if (raw.length < MIN_CHARS) continue;

    // Prepend tail overlap from previous section (cross-reference continuity)
    const text = (prevTail ? prevTail + "\n" : "") + raw;
    prevTail = raw.slice(-200);

    const { ref, title } = parseSectionRef(raw);

    // Build the full section reference with code prefix
    const corpusPrefix = meta.corpusKey.split(":")[0]; // 'CBC', 'CRC', etc.
    const fullRef = ref ? `${corpusPrefix} ${ref}` : null;

    // Split oversized sections at paragraph boundaries
    const subChunks = splitAtParagraphs(text, MAX_CHARS);

    for (let j = 0; j < subChunks.length; j++) {
      const chunkText = subChunks[j].trim();
      if (chunkText.length < MIN_CHARS) continue;

      chunks.push({
        corpus_key: meta.corpusKey,
        jurisdiction_key: meta.jurisdictionKey,
        code_name: meta.codeName,
        part: meta.part,
        chapter: meta.chapter,
        chapter_title: meta.chapterTitle,
        section_ref: fullRef ?? (meta.chapter ? `${corpusPrefix} ${meta.chapter}` : null),
        section_title: j === 0 ? title : null,  // only first sub-chunk gets the title
        subsection: j > 0 ? `${ref ?? ""}[part ${j + 1}]` : null,
        chunk_text: chunkText,
        token_count: estimateTokens(chunkText),
        source_url: meta.sourceUrl,
        code_year: meta.codeYear,
        content_hash: hashText(chunkText),
      });
    }
  }

  return chunks;
}

// =====================================================================
// Split text at paragraph boundaries to stay within MAX_CHARS
// =====================================================================
function splitAtParagraphs(text: string, maxChars: number): string[] {
  if (text.length <= maxChars) return [text];

  const paragraphs = text.split(/\n{2,}/);
  const parts: string[] = [];
  let current = "";

  for (const para of paragraphs) {
    if ((current + "\n\n" + para).length > maxChars && current.length > 0) {
      parts.push(current.trim());
      current = para;
    } else {
      current = current ? current + "\n\n" + para : para;
    }
  }
  if (current.trim().length > 0) parts.push(current.trim());
  return parts.length > 0 ? parts : [text.slice(0, maxChars)];
}

// =====================================================================
// Normalize a section ref for matching (lowercase, strip spaces)
// =====================================================================
export function normalizeSectionRef(ref: string): string {
  return ref.toLowerCase().replace(/\s+/g, "").trim();
}
