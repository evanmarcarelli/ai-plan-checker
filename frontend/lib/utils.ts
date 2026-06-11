import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Sanitize a post-auth ?redirect= target. Only same-site paths are allowed:
 *  "https://evil.com", "//evil.com", and "/\evil.com" (backslash trick) would
 *  all leave the site, so anything that isn't a plain internal path falls
 *  back to /dashboard. */
export function safeRedirect(target: string | null | undefined): string {
  if (!target) return "/dashboard";
  if (!target.startsWith("/") || target.startsWith("//") || target.startsWith("/\\")) {
    return "/dashboard";
  }
  return target;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function getStatusColor(status: string): string {
  switch (status) {
    case "compliant": return "text-emerald-600 bg-emerald-50 border-emerald-200";
    case "non_compliant": return "text-red-600 bg-red-50 border-red-200";
    case "needs_review": return "text-amber-600 bg-amber-50 border-amber-200";
    case "not_applicable": return "text-slate-500 bg-slate-50 border-slate-200";
    default: return "text-slate-600 bg-slate-50 border-slate-200";
  }
}

export function getStatusLabel(status: string): string {
  switch (status) {
    case "compliant": return "Compliant";
    case "non_compliant": return "Non-Compliant";
    case "needs_review": return "Needs Review";
    case "not_applicable": return "N/A";
    default: return status;
  }
}

export function getSeverityColor(severity: string): string {
  switch (severity) {
    case "critical": return "text-red-700 bg-red-100 border-red-300";
    case "high": return "text-orange-700 bg-orange-100 border-orange-300";
    case "medium": return "text-amber-700 bg-amber-100 border-amber-300";
    case "low": return "text-emerald-700 bg-emerald-100 border-emerald-300";
    default: return "text-slate-600 bg-slate-100 border-slate-200";
  }
}

// Use lucide-react icons in components instead of emoji strings.
// Kept as no-op for any legacy callers; returns empty string.
export function getCategoryIcon(_category: string): string {
  return "";
}

export function getCategoryLabel(category: string): string {
  return category
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
