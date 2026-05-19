import { createClient } from "./supabase/client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export const API_URL = `${API_BASE}/api/v1`;
export const WS_URL = `${WS_BASE}/api/v1`;

async function authHeaders(): Promise<Record<string, string>> {
  if (typeof window === "undefined") return {};
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};
}

export interface UserProfile {
  id: string;
  email: string;
  credits_remaining: number;
  display_name?: string;
  firm_name?: string;
  plan_tier?: "free" | "starter" | "professional" | "unlimited";
  plan_credits_per_month?: number;
  subscription_status?: string | null;
  subscription_current_period_end?: string | null;
}

export async function createCheckoutSession(plan: "starter" | "professional" | "unlimited"): Promise<{ url: string }> {
  const headers = { ...(await authHeaders()), "Content-Type": "application/json" };
  const res = await fetch(`${API_URL}/billing/checkout`, {
    method: "POST",
    headers,
    body: JSON.stringify({ plan }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Checkout failed: ${res.status}`);
  }
  return res.json();
}

export async function createPortalSession(): Promise<{ url: string }> {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/billing/portal`, { method: "POST", headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Portal failed: ${res.status}`);
  }
  return res.json();
}

export async function exportMyData(): Promise<void> {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/me/export`, { headers });
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "up2code-data-export.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function deleteMyAccount(): Promise<void> {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/me`, { method: "DELETE", headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Delete failed: ${res.status}`);
  }
}

export async function getMe(): Promise<UserProfile> {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/me`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch profile: ${res.status}`);
  return res.json();
}

export interface UploadResponse {
  job_id: string;
  message: string;
  filename: string;
  file_size: number;
}

export interface AgentLog {
  timestamp: string;
  agent: string;
  level: string;
  message: string;
  data?: Record<string, unknown>;
}

export interface Jurisdiction {
  city?: string;
  county?: string;
  state?: string;
  state_code?: string;
  country?: string;
  governing_authority?: string;
  seismic_zone?: string;
  wind_zone?: string;
  flood_zone?: string;
  confidence?: number;
}

export interface CodeRequirement {
  code_id: string;
  code_name: string;
  section: string;
  description: string;
  category: string;
  requirement_type: string;
  min_value?: number;
  max_value?: number;
  unit?: string;
  jurisdiction_specific: boolean;
}

export interface ComplianceFinding {
  finding_id: string;
  code_requirement: CodeRequirement;
  status: "compliant" | "non_compliant" | "needs_review" | "not_applicable";
  plan_value?: string;
  required_value?: string;
  description: string;
  recommendation?: string;
  severity: "critical" | "high" | "medium" | "low";
  category: string;
}

export interface ComplianceSummary {
  total_checks: number;
  compliant: number;
  non_compliant: number;
  needs_review: number;
  not_applicable: number;
  compliance_score: number;
  critical_issues: number;
  high_issues: number;
  medium_issues: number;
  low_issues: number;
}

export interface ExtractedPlanData {
  project_name?: string;
  project_address?: string;
  plan_type?: string;
  architect?: string;
  occupancy_type?: string;
  construction_type?: string;
  building_height?: number;
  building_area?: number;
  dimensions?: Record<string, unknown>;
  elements?: { element_type: string; description: string }[];
  materials?: string[];
}

export interface ComplianceReport {
  report_id: string;
  job_id: string;
  generated_at: string;
  jurisdiction?: Jurisdiction;
  plan_data?: ExtractedPlanData;
  findings: ComplianceFinding[];
  summary: ComplianceSummary;
  recommendations: string[];
  code_versions: Record<string, string>;
  sources_used: string[];
  auditor_notes?: string;
}

export interface JobStatus {
  job_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  progress: number;
  current_agent?: string;
  agents_completed: string[];
  error?: string;
  report?: ComplianceReport;
  logs: AgentLog[];
}

// ─────────────────────────────────────────────────────────
// API functions
// ─────────────────────────────────────────────────────────

export async function uploadPlan(
  file: File,
  onProgress?: (pct: number) => void,
  onStatus?: (msg: string) => void
): Promise<UploadResponse> {
  // Step 1: upload directly to Supabase Storage (bypass our backend's size limit).
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error("Not signed in");

  const uniq = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const storagePath = `${user.id}/${uniq}.pdf`;

  onStatus?.("Uploading PDF…");
  onProgress?.(10);
  const { error: upErr } = await supabase
    .storage
    .from("plan-uploads")
    .upload(storagePath, file, { contentType: "application/pdf", upsert: false });
  if (upErr) throw new Error(`Upload failed: ${upErr.message}`);
  onProgress?.(90);

  // Step 2: tell the backend the file is ready.
  // Retry on transient network errors (Render Free cold-start takes ~30-60s
  // to wake the dyno; the first POST after idle can fail before wake-up).
  const headers = { ...(await authHeaders()), "Content-Type": "application/json" };
  const body = JSON.stringify({
    storage_path: storagePath,
    filename: file.name,
    file_size: file.size,
  });

  // Render Free dynos can take a full 90 seconds to wake up from sleep.
  // We give each attempt 2 minutes, and try up to 4 times with growing
  // backoff. Worst case the user waits ~3 minutes on a fully cold start,
  // but they see "Server is waking up…" the whole time rather than a fail.
  const MAX_ATTEMPTS = 4;
  const TIMEOUT_MS = 120_000;
  const BACKOFF = [0, 15_000, 30_000, 30_000];

  let lastErr: unknown = null;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    if (BACKOFF[attempt - 1]) await new Promise((r) => setTimeout(r, BACKOFF[attempt - 1]));
    if (attempt > 1) onStatus?.(`Server is waking up (attempt ${attempt}/${MAX_ATTEMPTS})…`);
    else onStatus?.("Starting review…");

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(`${API_URL}/upload`, {
        method: "POST",
        headers,
        body,
        signal: controller.signal,
      });
      clearTimeout(timer);

      // 5xx + 429: worth retrying. Other 4xx: surface error to user.
      if (res.status >= 500 || res.status === 429) {
        lastErr = new Error(`server responded ${res.status}`);
        if (attempt < MAX_ATTEMPTS) continue;
      }

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        await supabase.storage.from("plan-uploads").remove([storagePath]).catch(() => {});
        throw new Error(errBody.detail || `Review start failed: ${res.status}`);
      }

      onProgress?.(100);
      onStatus?.(undefined as unknown as string);
      return res.json();
    } catch (e) {
      clearTimeout(timer);
      lastErr = e;
      // Network/abort errors are retried. Anything else we re-throw.
      const msg = e instanceof Error ? e.message.toLowerCase() : String(e);
      const isNetwork = msg.includes("fetch") || msg.includes("abort") || msg.includes("network");
      if (!isNetwork || attempt === MAX_ATTEMPTS) {
        await supabase.storage.from("plan-uploads").remove([storagePath]).catch(() => {});
        throw new Error(
          isNetwork
            ? "Couldn't reach the server after several tries. It may be temporarily down — please try again in a minute."
            : (lastErr instanceof Error ? lastErr.message : "Upload failed")
        );
      }
    }
  }

  // Unreachable, but TypeScript wants a return
  throw new Error("Upload failed");
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/jobs/${jobId}`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch job: ${res.status}`);
  return res.json();
}

export async function listJobs(): Promise<{ jobs: Array<{ id: string; filename: string; status: string; progress: number; created_at: string; summary?: ComplianceSummary }> }> {
  const headers = await authHeaders();
  const res = await fetch(`${API_URL}/jobs`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch jobs: ${res.status}`);
  return res.json();
}

export function getExportUrl(jobId: string, format: "pdf" | "csv"): string {
  return `${API_URL}/jobs/${jobId}/export/${format}`;
}

export function createWebSocket(jobId: string): WebSocket {
  return new WebSocket(`${WS_URL}/ws/${jobId}`);
}
