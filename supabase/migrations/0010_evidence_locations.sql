-- =====================================================================
-- 0010 — Evidence locations for PDF annotation
--
-- Adds the per-page text-block index that powers the annotation viewer:
-- every finding can carry a bounding box pointing back at the exact
-- region on the planset where the evidence (or violation) lives.
--
-- Shape of text_blocks:
--   [
--     {
--       "page": 1,                        -- 1-indexed PDF page
--       "text": "Construction Type: V-B", -- verbatim block text
--       "bbox": {                         -- normalized 0..1 PDF coords
--         "x": 0.12, "y": 0.18,
--         "w": 0.34, "h": 0.04
--       },
--       "sheet": "Code Analysis"          -- optional sheet name if known
--     },
--     ...
--   ]
--
-- Populated by the extraction step:
--   - native-text PDFs → pdfjs-dist on the client/server
--   - scanned PDFs    → Textract Block.Geometry.BoundingBox
--
-- Triage runner (evaluate.ts) reads this column to attach
-- evidence_location to each finding's report payload.
-- =====================================================================

alter table public.submittal_files
  add column if not exists text_blocks jsonb;

comment on column public.submittal_files.text_blocks is
  'Per-page text spans with bounding boxes (normalized 0..1). Drives PDF annotation overlays in the reviewer dashboard. Shape: [{page, text, bbox:{x,y,w,h}, sheet?}].';

-- GIN index on text_blocks for fast keyword search inside specific files.
-- Used by the citation gate when looking up which page a verbatim
-- snippet appears on without scanning extracted_text linearly.
create index if not exists submittal_files_text_blocks_gin
  on public.submittal_files using gin (text_blocks jsonb_path_ops);
