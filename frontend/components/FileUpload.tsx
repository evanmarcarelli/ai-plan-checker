"use client";

import { useCallback, useState } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { Upload, FileText, X, AlertCircle, MapPin, Loader2, CheckCircle2 } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { formatFileSize } from "@/lib/utils";
import { resolveSite, type SiteResolution } from "@/lib/api";

interface Props {
  onUpload: (file: File, projectAddress?: string) => void;
  isUploading: boolean;
  uploadProgress: number;
  uploadStatus?: string;
}

/** Site overlays as short chips for the pre-check card — the warnings list
 *  below them carries the full sentences; these are the at-a-glance flags. */
function overlayChips(r: SiteResolution): string[] {
  const o = r.overlays;
  if (!o) return [];
  const chips: string[] = [];
  if (o.fire_hazard?.in_zone)
    chips.push(`${o.fire_hazard.severity ?? ""} fire hazard zone (${o.fire_hazard.responsibility ?? "?"})`.trim());
  if (o.flood?.in_sfha) chips.push(`Flood zone ${o.flood.zone ?? ""}`.trim());
  if (o.coastal?.in_zone) chips.push("Coastal Zone");
  if (o.hillside?.in_zone) chips.push("Hillside Ordinance");
  if (o.hpoz?.in_zone) chips.push(o.hpoz.name ? `HPOZ: ${o.hpoz.name}` : "HPOZ");
  if (o.methane?.in_zone) chips.push(o.methane.kind ?? "Methane Zone");
  if (o.liquefaction?.in_zone) chips.push("Liquefaction zone");
  return chips;
}

export default function FileUpload({ onUpload, isUploading, uploadProgress, uploadStatus }: Props) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Project address pre-check. Optional, but when filled it pins the
  // jurisdiction + code editions server-side (instead of the pipeline
  // guessing them off the title block) and shows the customer which code
  // stack applies before they spend a credit.
  const [address, setAddress] = useState("");
  const [resolution, setResolution] = useState<SiteResolution | null>(null);
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);

  const runResolve = useCallback(async (value: string) => {
    const trimmed = value.trim();
    if (trimmed.length < 8) return;
    if (resolution && resolution.address.input === trimmed) return; // already resolved
    setResolving(true);
    setResolveError(null);
    try {
      const r = await resolveSite(trimmed);
      setResolution(r);
    } catch (e) {
      // Lookup failure never blocks the upload — the pipeline falls back to
      // reading the location from the plans.
      setResolution(null);
      setResolveError(e instanceof Error ? e.message : "Address lookup failed");
    } finally {
      setResolving(false);
    }
  }, [resolution]);

  // Storage tier caps every file at ~50 MB. Compress before uploading anything bigger.
  const MAX_BYTES = 49 * 1024 * 1024;

  const onDrop = useCallback(
    (accepted: File[], rejected: FileRejection[]) => {
      setError(null);
      if (rejected.length > 0) {
        setError(rejected[0]?.errors[0]?.message || "Invalid file");
        return;
      }
      const file = accepted[0];
      if (!file) return;

      if (file.size > MAX_BYTES) {
        const mb = (file.size / 1024 / 1024).toFixed(1);
        setError(
          `This PDF is ${mb} MB — we currently support up to 49 MB per file. ` +
            `Compress it first (Adobe Acrobat → File → Reduce File Size, or smallpdf.com/compress-pdf), ` +
            `then try again.`
        );
        return;
      }
      setSelectedFile(file);
    },
    [MAX_BYTES]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    maxSize: 100 * 1024 * 1024,
    multiple: false,
    disabled: isUploading,
  });

  const handleSubmit = () => {
    if (selectedFile && !isUploading) {
      onUpload(selectedFile, address.trim() || undefined);
    }
  };

  const handleRemove = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedFile(null);
    setError(null);
  };

  return (
    <div className="w-full space-y-4">
      {/* Drop zone — subtle hover lift makes the dashboard feel responsive
          even before the user touches it. We wrap a motion.div AROUND the
          dropzone (instead of spreading getRootProps onto motion.div) so
          framer-motion's onDrag prop type doesn't collide with
          react-dropzone's onDrag (Mouse/Touch/Pointer vs DragEvent) — that
          collision breaks `next build`. */}
      <motion.div
        whileHover={isUploading ? undefined : { scale: 1.005 }}
        whileTap={isUploading ? undefined : { scale: 0.995 }}
        transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
      >
      <div
        {...getRootProps()}
        className={`upload-zone relative overflow-hidden rounded-xl p-8 sm:p-12 cursor-pointer text-center outline-none
          ${isDragActive ? "drag-over" : ""}
          ${isUploading ? "cursor-not-allowed opacity-60" : ""}
        `}
      >
        <input {...getInputProps()} />

        {/* Blueprint-texture moment — a still SVG echo of the marketing hero's
            plan. Sits behind the content at low opacity so the dashboard
            narratively answers the homepage's promise ("plans → buildings"). */}
        {!selectedFile && (
          <BlueprintBackdrop />
        )}

        <div className="relative flex flex-col items-center gap-4">
          <div
            className={`w-14 h-14 rounded-xl flex items-center justify-center transition-transform duration-200
              ${isDragActive ? "scale-110" : ""}`}
            style={{
              background: isDragActive ? "var(--accent-soft)" : "var(--bg-card)",
              border: `1px solid ${isDragActive ? "var(--accent)" : "var(--border)"}`,
            }}
          >
            <Upload
              className="w-6 h-6"
              style={{ color: isDragActive ? "var(--accent)" : "var(--text-muted)" }}
            />
          </div>

          {selectedFile ? (
            <div className="space-y-1">
              <div className="flex items-center gap-2 justify-center">
                <FileText className="w-4 h-4" style={{ color: "var(--accent)" }} />
                <span className="text-[14px] font-medium" style={{ color: "var(--text-primary)" }}>
                  {selectedFile.name}
                </span>
                {!isUploading && (
                  <button
                    onClick={handleRemove}
                    className="p-0.5 rounded-md hover:bg-black/[0.04] transition-colors"
                  >
                    <X className="w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} />
                  </button>
                )}
              </div>
              <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                {formatFileSize(selectedFile.size)} · PDF
              </p>
            </div>
          ) : (
            <div>
              <p
                className="text-[18px] font-light leading-snug tracking-[-0.01em] mb-1"
                style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
              >
                {isDragActive ? (
                  <>Drop your PDF here</>
                ) : (
                  <>
                    Drop a PDF.{" "}
                    <span className="font-semibold">Get a structured review</span>{" "}
                    in 90 seconds.
                  </>
                )}
              </p>
              <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                Click to browse · PDF only · up to 49 MB
              </p>
            </div>
          )}
        </div>
      </div>
      </motion.div>

      {/* Project address — appears once a file is picked. Resolves on blur /
          Enter via POST /site/resolve and shows the jurisdiction + code stack
          the review will use, so any "we don't cover this yet" surprise lands
          BEFORE a credit is spent, not in the report. */}
      <AnimatePresence>
        {selectedFile && (
          <motion.div
            key="address"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="space-y-2"
          >
            <label
              htmlFor="project-address"
              className="block text-[12px] font-medium px-1"
              style={{ color: "var(--text-muted)" }}
            >
              Project address{" "}
              <span className="font-normal">
                (optional — pins the jurisdiction and code editions for the review)
              </span>
            </label>
            <div className="relative">
              <MapPin
                className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
                style={{ color: "var(--text-muted)" }}
              />
              <input
                id="project-address"
                type="text"
                value={address}
                disabled={isUploading}
                placeholder="200 N Spring St, Los Angeles, CA"
                autoComplete="street-address"
                onChange={(e) => {
                  setAddress(e.target.value);
                  // Stale results are worse than none — clear the card the
                  // moment the input no longer matches what was resolved.
                  if (resolution && resolution.address.input !== e.target.value.trim()) {
                    setResolution(null);
                  }
                  setResolveError(null);
                }}
                onBlur={() => runResolve(address)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    runResolve(address);
                  }
                }}
                className="w-full pl-9 pr-9 py-2.5 rounded-lg text-[13px] outline-none transition-colors focus:border-[var(--accent)]"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
              {resolving && (
                <Loader2
                  className="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 animate-spin"
                  style={{ color: "var(--text-muted)" }}
                />
              )}
            </div>

            {/* Resolution card */}
            {resolution && !resolving && (
              <div
                className="px-4 py-3 rounded-xl space-y-1.5 text-[13px]"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                }}
              >
                {!resolution.geocode_failed && (
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 flex-shrink-0" style={{ color: "var(--accent)" }} />
                    <span className="font-medium" style={{ color: "var(--text-primary)" }}>
                      {resolution.adoption?.authority ||
                        [resolution.jurisdiction.city || resolution.jurisdiction.county,
                         resolution.jurisdiction.state_code].filter(Boolean).join(", ") ||
                        "Jurisdiction resolved"}
                    </span>
                  </div>
                )}
                {!resolution.geocode_failed && resolution.adoption?.headline && (
                  <p style={{ color: "var(--text-muted)" }}>
                    Will be checked against: {resolution.adoption.headline}
                    {Object.keys(resolution.adoption.amendments || {}).length > 0 && " + local amendments"}
                  </p>
                )}
                {overlayChips(resolution).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    {overlayChips(resolution).map((chip) => (
                      <span
                        key={chip}
                        className="text-[11px] font-medium px-2 py-0.5 rounded-md"
                        style={{
                          background: "var(--needs-review-bg)",
                          color: "var(--needs-review)",
                        }}
                      >
                        {chip}
                      </span>
                    ))}
                  </div>
                )}
                {resolution.warnings.map((w) => (
                  <p key={w} className="flex items-start gap-2" style={{ color: "var(--needs-review, #b45309)" }}>
                    <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                    {w}
                  </p>
                ))}
              </div>
            )}
            {resolveError && !resolving && (
              <p className="px-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
                Couldn&apos;t look up that address ({resolveError}). You can still run the
                check — the location will be read from the plans.
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Error message */}
      {error && (
        <div
          className="flex items-center gap-2 px-4 py-3 rounded-xl text-[13px]"
          style={{
            background: "var(--non-compliant-bg)",
            border: "1px solid rgba(185, 28, 28, 0.25)",
            color: "var(--non-compliant)",
          }}
        >
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Upload progress */}
      {isUploading && (
        <div className="space-y-2">
          <div className="flex justify-between text-xs" style={{ color: "var(--text-muted)" }}>
            <span>{uploadStatus || "Uploading…"}</span>
            <span>{uploadProgress}%</span>
          </div>
          <div
            className="h-1.5 rounded-full overflow-hidden"
            style={{ background: "var(--bg-elevated)" }}
          >
            <div
              className="h-full rounded-full transition-all duration-300 progress-bar-active"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      )}

      {/* Submit button — slides in from below when a file is selected.
          AnimatePresence handles the unmount gracefully if the user removes
          the file before submitting. */}
      <AnimatePresence>
        {selectedFile && !isUploading && (
          <motion.button
            key="submit"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            onClick={handleSubmit}
            className="w-full py-3 rounded-lg font-semibold text-[14px] flex items-center justify-center gap-2 btn-primary"
            style={{ fontFamily: "var(--font-display)" }}
          >
            <Upload className="w-4 h-4" />
            Analyze plan set
          </motion.button>
        )}
      </AnimatePresence>

      {/* Supported codes — quiet inline list, no card. */}
      <div className="px-1 pt-3">
        <p
          className="text-[11px] font-semibold tracking-[0.18em] uppercase mb-2"
          style={{ color: "var(--text-muted)" }}
        >
          Checks against
        </p>
        <div className="flex flex-wrap gap-1.5">
          {["IBC 2021", "IFC 2021", "NEC 2023", "IPC 2021", "IMC 2021", "ADA 2010", "State amendments"].map((code) => (
            <span
              key={code}
              className="text-[11px] font-medium px-2 py-0.5 rounded-md"
              style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
            >
              {code}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Blueprint backdrop ────────────────────────────────────────────
// A still echo of the marketing hero's plan — same black-and-white aesthetic
// at 50% opacity so the upload zone reads as the natural continuation of the
// scroll narrative. Pure SVG so it renders crisply at any size with no extra
// network requests.
function BlueprintBackdrop() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 800 280"
      preserveAspectRatio="xMidYMid slice"
      className="pointer-events-none absolute inset-0 w-full h-full"
      style={{ opacity: 0.5 }}
    >
      {/* Faint grid */}
      <defs>
        <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
          <path d="M 32 0 L 0 0 0 32" fill="none" stroke="rgba(0,0,0,0.05)" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width="800" height="280" fill="url(#grid)" />
      {/* Sheet borders */}
      <rect x="40" y="24" width="720" height="232" fill="none" stroke="rgba(0,0,0,0.18)" strokeWidth="1.5" />
      <rect x="50" y="34" width="700" height="212" fill="none" stroke="rgba(0,0,0,0.10)" strokeWidth="0.8" />
      {/* Title-block stamp */}
      <text x="400" y="60" textAnchor="middle" fontSize="12" fontFamily="Inter, system-ui, sans-serif" fontWeight="600" fill="rgba(0,0,0,0.32)">
        TYPICAL FLOOR PLAN — ARCHITECHTURA PLAN REVIEW
      </text>
      {/* Footprints */}
      <rect x="170" y="100" width="240" height="120" fill="none" stroke="rgba(0,0,0,0.30)" strokeWidth="1.8" />
      <rect x="440" y="120" width="180" height="100" fill="none" stroke="rgba(0,0,0,0.30)" strokeWidth="1.8" />
      {/* Dashed tower-core projections */}
      <rect x="200" y="120" width="180" height="80" fill="none" stroke="rgba(0,0,0,0.22)" strokeWidth="1" strokeDasharray="5 4" />
      <rect x="460" y="138" width="140" height="64" fill="none" stroke="rgba(0,0,0,0.22)" strokeWidth="1" strokeDasharray="5 4" />
      {/* Interior partitions */}
      <line x1="290" y1="100" x2="290" y2="220" stroke="rgba(0,0,0,0.20)" strokeWidth="0.8" />
      <line x1="170" y1="160" x2="410" y2="160" stroke="rgba(0,0,0,0.20)" strokeWidth="0.8" />
      <line x1="530" y1="120" x2="530" y2="220" stroke="rgba(0,0,0,0.20)" strokeWidth="0.8" />
      {/* Column grid */}
      {[200, 240, 280, 320, 360, 400, 460, 500, 540, 580].map((cx, i) => (
        <g key={i}>
          <circle cx={cx} cy={120} r="2" fill="rgba(0,0,0,0.30)" />
          <circle cx={cx} cy={200} r="2" fill="rgba(0,0,0,0.30)" />
        </g>
      ))}
      {/* Dimension hash marks */}
      <line x1="170" y1="80" x2="410" y2="80" stroke="rgba(0,0,0,0.22)" strokeWidth="0.6" />
      <line x1="170" y1="76" x2="170" y2="84" stroke="rgba(0,0,0,0.22)" strokeWidth="0.6" />
      <line x1="410" y1="76" x2="410" y2="84" stroke="rgba(0,0,0,0.22)" strokeWidth="0.6" />
      <text x="290" y="74" textAnchor="middle" fontSize="9" fontFamily="DM Mono, monospace" fill="rgba(0,0,0,0.30)">
        66'-0"
      </text>
    </svg>
  );
}
