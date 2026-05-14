"use client";

import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Upload, FileText, X, AlertCircle } from "lucide-react";
import { formatFileSize } from "@/lib/utils";

interface Props {
  onUpload: (file: File) => void;
  isUploading: boolean;
  uploadProgress: number;
}

export default function FileUpload({ onUpload, isUploading, uploadProgress }: Props) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onDrop = useCallback(
    (accepted: File[], rejected: { errors: { message: string }[] }[]) => {
      setError(null);
      if (rejected.length > 0) {
        setError(rejected[0]?.errors[0]?.message || "Invalid file");
        return;
      }
      if (accepted[0]) {
        setSelectedFile(accepted[0]);
      }
    },
    []
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
      onUpload(selectedFile);
    }
  };

  const handleRemove = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedFile(null);
    setError(null);
  };

  return (
    <div className="w-full space-y-4">
      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={`upload-zone rounded-2xl p-10 cursor-pointer text-center outline-none
          ${isDragActive ? "drag-over" : ""}
          ${isUploading ? "cursor-not-allowed opacity-60" : ""}
        `}
      >
        <input {...getInputProps()} />

        <div className="flex flex-col items-center gap-4">
          {/* Icon */}
          <div
            className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-all
              ${isDragActive ? "scale-110" : ""}`}
            style={{
              background: isDragActive
                ? "rgba(79, 126, 255, 0.15)"
                : "rgba(255,255,255,0.04)",
              border: `1.5px solid ${isDragActive ? "var(--accent)" : "var(--border)"}`,
            }}
          >
            <Upload
              className={`w-7 h-7 transition-colors ${isDragActive ? "text-blue-400" : ""}`}
              style={{ color: isDragActive ? undefined : "var(--text-muted)" }}
            />
          </div>

          {selectedFile ? (
            <div className="space-y-1">
              <div className="flex items-center gap-2 justify-center">
                <FileText className="w-4 h-4 text-blue-400" />
                <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                  {selectedFile.name}
                </span>
                {!isUploading && (
                  <button
                    onClick={handleRemove}
                    className="p-0.5 rounded hover:bg-white/10 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" style={{ color: "var(--text-muted)" }} />
                  </button>
                )}
              </div>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {formatFileSize(selectedFile.size)} · PDF
              </p>
            </div>
          ) : (
            <div>
              <p className="text-sm font-medium mb-1" style={{ color: "var(--text-primary)" }}>
                {isDragActive ? "Drop your PDF here" : "Drag & drop your plan set"}
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                or click to browse · PDF only · Max 100MB · Auto-compressed if needed
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div
          className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm"
          style={{
            background: "var(--non-compliant-bg)",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "#f87171",
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
            <span>Uploading…</span>
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

      {/* Submit button */}
      {selectedFile && !isUploading && (
        <button
          onClick={handleSubmit}
          className="w-full py-3.5 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all glow-blue"
          style={{
            background: "linear-gradient(135deg, var(--accent) 0%, #818cf8 100%)",
            color: "white",
            fontFamily: "var(--font-display)",
          }}
        >
          <Upload className="w-4 h-4" />
          Analyze Plan Set
        </button>
      )}

      {/* Supported codes info */}
      <div
        className="rounded-xl p-4 text-xs"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <p className="font-medium mb-2" style={{ color: "var(--text-secondary)" }}>
          Checks against:
        </p>
        <div className="flex flex-wrap gap-2">
          {["IBC 2021", "IFC 2021", "NEC 2023", "IPC 2021", "IMC 2021", "ADA 2010", "State Amendments"].map((code) => (
            <span
              key={code}
              className="px-2 py-0.5 rounded-md"
              style={{
                background: "rgba(79, 126, 255, 0.08)",
                border: "1px solid rgba(79, 126, 255, 0.15)",
                color: "var(--accent-bright)",
              }}
            >
              {code}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
