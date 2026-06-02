// =====================================================================
// PDF text + coordinate extractor.
//
// Given the raw bytes of a PDF, returns:
//   - extracted_text  with [PAGE:N] markers for downstream regex/LLM
//   - text_blocks     with normalized 0..1 bounding boxes (top-left origin)
//                     for the PdfAnnotationViewer overlay layer
//   - page_count      number of PDF pages
//   - has_text_layer  true when ANY page yielded text via the text layer
//                     (false ⇒ scanned PDF, needs OCR; this extractor
//                     does not OCR — Textract wiring is a separate ticket)
//
// Implementation notes:
//   - Uses pdfjs-dist 4.x legacy build via npm: specifier. The legacy
//     build is the most Deno/Node-compatible (no canvas, no DOM).
//   - PDF coordinate system has y-origin bottom-left. The viewer expects
//     top-left. We flip y here so the consumer never has to.
//   - Each pdfjs "item" becomes one text_block. Grouping items into
//     larger spans is a future optimization (would reduce JSONB size by
//     ~5-10x on dense plan sets, but the current shape is correct).
//   - Empty/whitespace-only items are dropped.
// =====================================================================

// deno-lint-ignore-file no-explicit-any
// @ts-ignore — pdfjs-dist's npm types don't always resolve under Deno
import * as pdfjsLib from "npm:pdfjs-dist@4.8.69/legacy/build/pdf.mjs";

export interface PdfTextBlock {
  page: number;                                         // 1-indexed
  text: string;
  bbox: { x: number; y: number; w: number; h: number }; // normalized 0..1, top-left origin
  sheet?: string;                                       // populated if we can infer a sheet name
}

export interface PdfExtractResult {
  extracted_text: string;
  text_blocks: PdfTextBlock[];
  page_count: number;
  has_text_layer: boolean;
}

const MIN_TEXT_LEN = 1;          // drop items shorter than this after trim
const MAX_BBOX_HEIGHT = 0.5;     // drop items reporting absurd heights (decoration glyphs)

// Sheet-name heuristic: look for a token matching "Sheet: <name>" or a
// title-block-style label like "A-101", "A0.01" near the top of the page.
// Cheap and best-effort — when nothing matches we leave sheet undefined.
const SHEET_NAME_RE = /\b(?:Sheet|SHEET):\s*([A-Z0-9.\-]+)/;
const SHEET_LABEL_RE = /^[A-Z]{1,3}-?\d{1,3}(?:\.\d{1,3})?$/;

function inferSheetName(text: string): string | undefined {
  const m = text.match(SHEET_NAME_RE);
  if (m) return m[1].trim();
  return undefined;
}

export async function extractPdf(bytes: Uint8Array): Promise<PdfExtractResult> {
  const loadingTask = (pdfjsLib as any).getDocument({
    data: bytes,
    // Don't try to load fonts from the filesystem — irrelevant for text extraction.
    disableFontFace: true,
    useSystemFonts: false,
  });
  const doc = await loadingTask.promise;
  const pageCount: number = doc.numPages;

  const pageTexts: string[] = [];
  const blocks: PdfTextBlock[] = [];
  let anyTextFound = false;

  for (let pageNum = 1; pageNum <= pageCount; pageNum++) {
    const page = await doc.getPage(pageNum);
    const viewport = page.getViewport({ scale: 1 });
    const vw = viewport.width;
    const vh = viewport.height;
    const content = await page.getTextContent();
    const items = (content.items ?? []) as any[];

    // Concatenate page text (with line breaks between items whose y
    // differs by more than a font height). This is good enough for
    // downstream regex/LLM consumption.
    let pageText = "";
    let lastY: number | null = null;
    let sheetGuess: string | undefined;

    for (const item of items) {
      const str = (item.str ?? "") as string;
      if (str.trim().length < MIN_TEXT_LEN) continue;

      // transform = [a, b, c, d, e, f]
      //   a, d = scale x/y; e = tx; f = ty (PDF origin: bottom-left)
      const t = item.transform as number[] | undefined;
      if (!t || t.length < 6) continue;
      const tx = t[4];
      const ty = t[5];
      const sy = Math.abs(t[3]) || Math.abs(t[0]) || 10;
      const itemWidthPdfUnits = (item.width as number | undefined) ?? sy * str.length * 0.5;

      // Normalize 0..1, FLIP y so origin is top-left to match the viewer.
      const bbox = {
        x: clamp01(tx / vw),
        y: clamp01(1 - (ty + sy) / vh),
        w: clamp01(itemWidthPdfUnits / vw),
        h: clamp01(sy / vh),
      };
      if (bbox.h > MAX_BBOX_HEIGHT) continue;
      if (bbox.w <= 0 || bbox.h <= 0) continue;

      // Line-break heuristic for pageText: when ty drops by > 1.5x font height.
      if (lastY !== null && Math.abs(ty - lastY) > sy * 1.5) {
        pageText += "\n";
      } else if (pageText && !pageText.endsWith(" ") && !pageText.endsWith("\n")) {
        pageText += " ";
      }
      pageText += str;
      lastY = ty;

      // First valid sheet-name guess sticks for the whole page.
      if (!sheetGuess) {
        const inferred = inferSheetName(str);
        if (inferred) sheetGuess = inferred;
        else if (SHEET_LABEL_RE.test(str.trim()) && bbox.y < 0.15) {
          sheetGuess = str.trim();
        }
      }

      blocks.push({
        page: pageNum,
        text: str,
        bbox,
        ...(sheetGuess ? { sheet: sheetGuess } : {}),
      });
    }

    if (pageText.trim().length > 0) {
      anyTextFound = true;
      const sheetLabel = sheetGuess ? ` Sheet: ${sheetGuess}` : "";
      pageTexts.push(`[PAGE:${pageNum}${sheetLabel}]\n${pageText.trim()}`);
    } else {
      // Still emit a marker so downstream knows the page exists (just empty).
      pageTexts.push(`[PAGE:${pageNum}]\n`);
    }

    // Free per-page resources promptly — large PDFs balloon memory otherwise.
    page.cleanup();
  }

  await doc.cleanup();
  await doc.destroy();

  return {
    extracted_text: pageTexts.join("\n\n"),
    text_blocks: blocks,
    page_count: pageCount,
    has_text_layer: anyTextFound,
  };
}

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}
