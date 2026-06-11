"use client";

import { useEffect, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";
import { uploadPlan, getJobStatus, createWebSocket, getExportUrl, getMe, listJobs } from "@/lib/api";
import type { AgentLog, UserProfile, JobStatus, JobListItem } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";
import FileUpload from "@/components/FileUpload";
import BrandMark from "@/components/BrandMark";
import AgentLogs from "@/components/AgentLogs";
import ComplianceReport from "@/components/ComplianceReport";
import RecentsRail from "@/components/RecentsRail";
import RaceTrack, { type NodeStatus } from "@/components/RaceTrack";
import Reveal from "@/components/Reveal";
import {
  Building2, Cpu, FileCheck, ChevronRight,
  Activity, CheckCircle2, AlertCircle, Clock, RotateCcw,
  Search, BookOpen, Landmark, Flame, Zap, Droplets, Wind,
  Accessibility, Leaf, Compass, Construction, Trees, ArrowRight, X, FileClock,
} from "lucide-react";

// ─── Department roster ────────────────────────────────────────────
// Pipeline shows 3 stages — but Stage 3 fans out into 10 parallel department reviewers.
const DEPARTMENT_AGENTS = [
  "Building & Safety", "Fire Department", "Electrical Inspector", "Plumbing Inspector",
  "Mechanical Inspector", "Accessibility (ADA / CBC 11B)", "Energy & Green Building",
  "Planning & Zoning", "Public Works", "Environmental",
];

const AGENTS = [
  { id: "Surveyor",    label: "Surveyor",       Icon: Search,    description: "Identifies jurisdiction from title block" },
  { id: "Librarian",   label: "Librarian",      Icon: BookOpen,  description: "Retrieves applicable building codes" },
  {
    id: "Departments", label: "10 Departments", Icon: Landmark,
    description: "Building Safety, Fire, Electrical, Plumbing, Mechanical, ADA, Energy, Zoning, Public Works, Environmental",
    isGroup: true,
    members: DEPARTMENT_AGENTS,
  },
];

// Marketing-grade department iconography — referenced by the empty-state rail.
const DEPARTMENTS = [
  { Icon: Building2,    label: "Building & Safety" },
  { Icon: Flame,         label: "Fire" },
  { Icon: Zap,           label: "Electrical" },
  { Icon: Droplets,      label: "Plumbing" },
  { Icon: Wind,          label: "Mechanical" },
  { Icon: Accessibility, label: "Accessibility" },
  { Icon: Leaf,          label: "Energy" },
  { Icon: Compass,       label: "Zoning" },
  { Icon: Construction,  label: "Public Works" },
  { Icon: Trees,         label: "Environmental" },
];

// Map the report's per-department verdicts onto RaceTrack node ids. Department
// names match the node ids 1:1 (see RACE_NODES); review_status is the backend's
// cleared|conditional|rejected|pending, which we fold into the 4 node states.
const REVIEW_TO_NODE: Record<string, NodeStatus> = {
  cleared: "compliant",
  conditional: "needs_review",
  rejected: "non_compliant",
  pending: "not_applicable",
};
function computeRaceResults(report: JobStatus["report"], status?: string): Record<string, NodeStatus> {
  const out: Record<string, NodeStatus> = {};
  const reviews = (report as unknown as
    { department_reviews?: Array<{ department: string; review_status: string }> } | undefined
  )?.department_reviews;
  for (const d of reviews || []) {
    const ns = REVIEW_TO_NODE[d.review_status];
    if (ns) out[d.department] = ns;
  }
  // Surveyor + Librarian aren't departments; if the run finished they cleared.
  if (status === "completed") {
    if (!out["Surveyor"]) out["Surveyor"] = "compliant";
    if (!out["Librarian"]) out["Librarian"] = "compliant";
  }
  return out;
}

// ─── Compact, chrome-free pipeline (header version) ──────────────
function AgentPipeline({
  completed,
  current,
}: {
  completed: string[];
  current?: string | null;
}) {
  return (
    <div className="flex items-center gap-1.5 sm:gap-2">
      {AGENTS.map((agent, i) => {
        const isGroup = !!(agent as { isGroup?: boolean }).isGroup;
        const members = (agent as { members?: string[] }).members || [];
        const doneCount = isGroup ? members.filter((m) => completed.includes(m)).length : 0;
        const isDone = isGroup
          ? doneCount === members.length && members.length > 0
          : completed.includes(agent.id);
        const isActive = isGroup
          ? !isDone && members.some((m) => m === current || completed.includes(m))
          : current === agent.id;

        // Subdued semantic chip styles — no card chrome on the pipeline.
        const tone = isDone
          ? { bg: "var(--compliant-bg)",  fg: "var(--compliant)",   ring: "rgba(21,128,61,0.20)" }
          : isActive
          ? { bg: "var(--accent-soft)",   fg: "var(--accent)",      ring: "rgba(47,91,255,0.22)" }
          : { bg: "transparent",          fg: "var(--text-muted)",  ring: "var(--border)" };

        return (
          <div key={agent.id} className="flex items-center gap-1.5 sm:gap-2">
            <div
              className={`relative flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[12px] font-medium ${isActive ? "agent-active" : ""}`}
              style={{ background: tone.bg, color: tone.fg, boxShadow: `0 0 0 1px ${tone.ring}` }}
            >
              <agent.Icon className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">
                {agent.label}
                {isGroup && isActive && (
                  <span className="ml-1 opacity-70 text-[11px]">({doneCount}/{members.length})</span>
                )}
              </span>
              {isDone && <CheckCircle2 className="w-3 h-3" />}
              {isActive && (
                <div className="w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
              )}
            </div>
            {i < AGENTS.length - 1 && (
              <ChevronRight
                className="w-3.5 h-3.5 flex-shrink-0"
                style={{ color: isDone ? "var(--compliant)" : "var(--border-bright)" }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Main Dashboard ─────────────────────────────────────────────────
export default function Dashboard() {
  const {
    jobId, jobStatus, isUploading, uploadProgress, logs,
    activeTab, wsConnected,
    setJobId, setJobStatus, setIsUploading, setUploadProgress,
    addLog, setLogs, setWsConnected, setActiveTab, reset,
  } = useAppStore();

  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  // True once the job reaches completed/failed — gates the WS→polling
  // fallback so a clean completion-close doesn't kick off needless polling.
  const terminalRef = useRef(false);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string>("");
  // Surfaced inline (not via alert) for upload failures and lost-connection.
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const router = useRouter();
  const [isAuthed, setIsAuthed] = useState<boolean | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobListItem[]>([]);
  const [recentsLoading, setRecentsLoading] = useState(true);
  const [recentsOpen, setRecentsOpen] = useState(false); // mobile drawer
  const [logsOpen, setLogsOpen] = useState(true);

  useEffect(() => {
    const sb = createClient();
    sb.auth.getSession().then(({ data: { session } }) => {
      setIsAuthed(!!session);
    }).catch(() => setIsAuthed(false));
  }, []);

  // Recent reports rail — load on auth, refresh whenever a job changes state
  // (so a just-finished review surfaces with its verdict dot).
  useEffect(() => {
    if (!isAuthed) return;
    listJobs()
      .then((r) => setRecentJobs(r.jobs))
      .catch(() => { /* rail is best-effort */ })
      .finally(() => setRecentsLoading(false));
  }, [isAuthed, jobStatus?.status, jobId]);

  // Reopen a past report from the rail.
  const openReport = (id: string) => {
    setJobId(id);
    getJobStatus(id)
      .then((s) => {
        setJobStatus(s);
        setActiveTab(s.status === "completed" ? "report" : "processing");
      })
      .catch(() => { /* surfaced by the report/processing views */ });
  };

  useEffect(() => {
    if (isAuthed) {
      getMe().then(setProfile).catch(() => setProfile(null));
    }
  }, [jobStatus, isAuthed]);

  const handleSignOut = async () => {
    const sb = createClient();
    await sb.auth.signOut();
    router.push("/login");
    router.refresh();
  };

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const markTerminal = (status: JobStatus) => {
    terminalRef.current = true;
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (status.status === "completed") setActiveTab("report");
  };

  // WebSocket is the primary, real-time channel. Polling is a FALLBACK,
  // started only if the socket never opens or drops before the job
  // finishes — so we don't fire duplicate requests when WS is healthy.
  const connectWebSocket = (id: string) => {
    let opened = false;
    try {
      const ws = createWebSocket(id);
      wsRef.current = ws;
      ws.onopen = () => { opened = true; setWsConnected(true); };
      ws.onclose = () => {
        setWsConnected(false);
        if (!terminalRef.current) startPolling(id); // dropped mid-review → fall back
      };
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "log" && msg.data) addLog(msg.data as AgentLog);
          if (msg.type === "status" && msg.data) {
            setJobStatus((prev) => prev ? { ...prev, ...msg.data } : msg.data);
          }
          if (msg.type === "completed" || msg.type === "failed") {
            // Mark terminal synchronously so the imminent socket close
            // doesn't trip the onclose→polling fallback before the async
            // getJobStatus below resolves.
            terminalRef.current = true;
            getJobStatus(id).then((status) => {
              setJobStatus(status);
              setLogs(status.logs);
              markTerminal(status);
            }).catch(() => {});
          }
        } catch {}
      };
      // If the socket never opens (a proxy/firewall blocks WS), fall back.
      setTimeout(() => { if (!opened && !terminalRef.current) startPolling(id); }, 3000);
    } catch {
      startPolling(id);
    }
  };

  const startPolling = (id: string) => {
    if (pollRef.current || terminalRef.current) return; // already polling / done
    let consecutiveFailures = 0;
    pollRef.current = setInterval(async () => {
      try {
        const status = await getJobStatus(id);
        consecutiveFailures = 0;
        setErrorBanner(null);
        setJobStatus(status);
        setLogs(status.logs);
        if (status.status === "completed" || status.status === "failed") {
          markTerminal(status);
        }
      } catch {
        // Surface a persistent outage instead of silently spinning forever.
        if (++consecutiveFailures >= 5) {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
          setErrorBanner("Lost connection to the server while tracking your review. It may still be running — refresh to check its status.");
        }
      }
    }, 1000);
  };

  const handleUpload = async (file: File) => {
    if (isAuthed === false) {
      router.push("/login?redirect=/dashboard");
      return;
    }
    setUploadedFile(file);
    setIsUploading(true);
    setUploadProgress(0);
    setUploadStatus("");
    setErrorBanner(null);
    terminalRef.current = false;
    try {
      const result = await uploadPlan(
        file,
        (pct) => setUploadProgress(pct),
        (msg) => setUploadStatus(msg || "")
      );
      setUploadProgress(100);
      setUploadStatus("");
      setJobId(result.job_id);
      setActiveTab("processing");
      const status = await getJobStatus(result.job_id);
      setJobStatus(status);
      connectWebSocket(result.job_id); // starts polling itself only if WS fails
    } catch (err) {
      setErrorBanner(`Upload failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  };

  const handleReset = () => {
    wsRef.current?.close();
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    terminalRef.current = false;
    setErrorBanner(null);
    setUploadedFile(null);
    reset();
  };

  const isProcessing = jobStatus?.status === "processing" || jobStatus?.status === "pending";
  const isCompleted = jobStatus?.status === "completed";
  const isFailed = jobStatus?.status === "failed";

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      {/* ── Header — sparse: brand + (optionally) the pipeline + Reset ── */}
      <header
        className="sticky top-0 z-30 backdrop-blur border-b"
        style={{ background: "rgba(247, 248, 250, 0.85)", borderColor: "var(--border)" }}
      >
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between gap-4">
          <button
            onClick={() => router.push("/")}
            className="flex items-center gap-2 flex-shrink-0 rounded-lg hover:opacity-80 transition-opacity duration-150"
            aria-label="Go to home page"
          >
            {/* Brand mark — geometric "A" with ascending arrow — then the wordmark */}
            <BrandMark size={24} style={{ color: "var(--text-primary)" }} />
            <span
              className="font-semibold text-[18px] tracking-[-0.025em]"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
            >
              Architechtura
            </span>
          </button>

          {(isProcessing || isCompleted) && (
            <div className="hidden md:flex flex-1 justify-center min-w-0">
              <AgentPipeline
                completed={jobStatus?.agents_completed || []}
                current={jobStatus?.current_agent}
              />
            </div>
          )}

          <div className="flex items-center gap-3 flex-shrink-0">
            {wsConnected && (
              <div className="hidden sm:flex items-center gap-1.5 text-[12px]" style={{ color: "var(--compliant)" }}>
                <div className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "var(--compliant)" }} />
                Live
              </div>
            )}
            <button
              onClick={() => setRecentsOpen(true)}
              className="lg:hidden flex items-center gap-1.5 text-[12px] font-medium px-3 py-1.5 rounded-lg btn-secondary"
              aria-label="Recent reports"
            >
              <FileClock className="w-3.5 h-3.5" />
              Recents
            </button>
            {jobId && (
              <button
                onClick={handleReset}
                className="flex items-center gap-1.5 text-[12px] font-medium px-3 py-1.5 rounded-lg btn-secondary"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                New check
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="flex">
        {/* ── Recent reports rail (persistent on desktop) ── */}
        <aside
          className="hidden lg:flex flex-col flex-shrink-0 w-[264px] sticky top-16 self-start border-r"
          style={{ height: "calc(100vh - 4rem)", borderColor: "var(--border)", background: "var(--bg-card)" }}
        >
          <RecentsRail jobs={recentJobs} activeJobId={jobId} onSelect={openReport} loading={recentsLoading} />
        </aside>

        {/* ── Recent reports drawer (mobile) ── */}
        {recentsOpen && (
          <div className="lg:hidden fixed inset-0 z-50 flex">
            <div className="absolute inset-0" style={{ background: "rgba(11,18,32,0.45)" }} onClick={() => setRecentsOpen(false)} />
            <aside className="relative w-[284px] max-w-[82vw] h-full flex flex-col border-r"
              style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}>
              <RecentsRail
                jobs={recentJobs}
                activeJobId={jobId}
                onSelect={(id) => { openReport(id); setRecentsOpen(false); }}
                loading={recentsLoading}
              />
            </aside>
          </div>
        )}

        <div className="flex-1 min-w-0">
        {/* ── Tab bar — only when an active job exists ── */}
      {jobId && (
        <div className="border-b" style={{ borderColor: "var(--border)" }}>
          <div className="max-w-7xl mx-auto px-6 flex gap-1 overflow-x-auto">
            {[
              { id: "upload",     label: "Upload",            icon: <FileCheck className="w-3.5 h-3.5" /> },
              { id: "processing", label: "Agent logs",        icon: <Cpu className="w-3.5 h-3.5" />, badge: isProcessing ? "LIVE" : undefined },
              { id: "report",     label: "Compliance report", icon: <Activity className="w-3.5 h-3.5" />, disabled: !isCompleted },
            ].map((tab) => {
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  disabled={tab.disabled}
                  onClick={() => !tab.disabled && setActiveTab(tab.id as "upload" | "processing" | "report")}
                  className={`flex items-center gap-2 px-4 py-3 text-[13px] border-b-2 transition-colors whitespace-nowrap
                    ${active ? "font-semibold" : tab.disabled ? "cursor-not-allowed" : "font-medium hover:text-[var(--text-primary)]"}
                  `}
                  style={{
                    borderColor: active ? "var(--accent)" : "transparent",
                    color: active
                      ? "var(--text-primary)"
                      : tab.disabled
                        ? "var(--text-muted)"
                        : "var(--text-secondary)",
                  }}
                >
                  {tab.icon}
                  {tab.label}
                  {tab.badge && (
                    <span
                      className="text-[10px] font-semibold tracking-wider px-1.5 py-0.5 rounded-md"
                      style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
                    >
                      {tab.badge}
                    </span>
                  )}
                  {tab.id === "report" && isCompleted && (
                    <CheckCircle2 className="w-3.5 h-3.5" style={{ color: "var(--compliant)" }} />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Content ── */}
      <main className="max-w-7xl mx-auto px-6 pt-10 pb-32">

        {/* Inline error banner — replaces the old blocking alert() for upload
            failures and lost-connection during a review. */}
        {errorBanner && (
          <div
            className="mb-6 flex items-start gap-3 px-4 py-3 rounded-xl text-[13px]"
            style={{
              background: "var(--non-compliant-bg)",
              border: "1px solid rgba(185, 28, 28, 0.25)",
              color: "var(--non-compliant)",
            }}
          >
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span className="flex-1">{errorBanner}</span>
            <button
              onClick={() => setErrorBanner(null)}
              className="p-0.5 rounded-md hover:bg-black/[0.06] transition-colors"
              aria-label="Dismiss"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* ── UPLOAD TAB ── */}
        {(activeTab === "upload" || !jobId) && (
          <div>
            {/* Editorial hero — same calm as the marketing page. */}
            <Reveal className="mb-12">
              <div
                className="inline-flex items-center gap-2 text-[11px] font-semibold tracking-[0.18em] uppercase mb-6"
                style={{ color: "var(--accent)" }}
              >
                Multi-agent AI for AEC
              </div>
              <h1
                className="text-[40px] sm:text-[44px] lg:text-[52px] font-light leading-[1.05] tracking-[-0.02em] max-w-3xl"
                style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
              >
                Run your next <span className="font-semibold">plan review</span>.
              </h1>
              <p
                className="mt-5 text-[16px] leading-[1.55] max-w-xl"
                style={{ color: "var(--text-secondary)" }}
              >
                Drop a PDF. Get a structured plan review in 90 seconds — every department, every chapter, every citation.
              </p>
              <div className="mt-7 flex items-center gap-3 flex-wrap">
                <span
                  className="inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1 rounded-md"
                  style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
                >
                  Multi-agent · 90s · cited
                </span>
                {!profile && isAuthed === true && (
                  <span className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                    First check free
                  </span>
                )}
              </div>
            </Reveal>

            {/* Upload zone — the one place we keep card chrome. */}
            <Reveal delay={0.08}>
              <FileUpload
                onUpload={handleUpload}
                isUploading={isUploading}
                uploadProgress={uploadProgress}
                uploadStatus={uploadStatus}
              />
            </Reveal>

            {/* Department roster rail — static reel of the 10 specialist
                reviewers. Lives below the upload zone on the empty state;
                same calm typography as the marketing page. */}
            <section className="mt-16">
              <Reveal>
                <div className="flex items-end justify-between mb-5">
                  <div>
                    <div
                      className="text-[11px] font-semibold tracking-[0.18em] uppercase mb-2"
                      style={{ color: "var(--accent)" }}
                    >
                      The reviewers
                    </div>
                    <h2
                      className="text-[28px] sm:text-[32px] font-light leading-[1.1] tracking-[-0.02em]"
                      style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
                    >
                      <span className="font-semibold">10 departments</span>, in parallel.
                    </h2>
                  </div>
                  <span className="text-[12px] hidden sm:block" style={{ color: "var(--text-muted)" }}>
                    Like a real city plan check
                  </span>
                </div>
              </Reveal>

              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {DEPARTMENTS.map((d, i) => (
                  <Reveal key={d.label} delay={i * 0.03} y={8}>
                    <div
                      className="flex flex-col items-center justify-center text-center p-4 rounded-xl"
                      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
                    >
                      <d.Icon className="w-5 h-5 mb-2" style={{ color: "var(--accent)" }} />
                      <div className="text-[12px] font-medium" style={{ color: "var(--text-primary)" }}>
                        {d.label}
                      </div>
                    </div>
                  </Reveal>
                ))}
              </div>
            </section>

          </div>
        )}

        {/* ── PROCESSING TAB ── */}
        {activeTab === "processing" && jobId && (
          <div className="space-y-6">
            {/* Race-track pipeline — the centerpiece */}
            <section className="p-5 sm:p-7 rounded-2xl" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center justify-between mb-5">
                <h3 className="text-[11px] font-semibold tracking-[0.18em] uppercase" style={{ color: "var(--text-muted)" }}>
                  Review pipeline
                </h3>
                {isProcessing && (
                  <span className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--accent)" }}>
                    <Clock className="w-3 h-3" /> Running
                  </span>
                )}
                {isCompleted && (
                  <span className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--compliant)" }}>
                    <CheckCircle2 className="w-3 h-3" /> Done
                  </span>
                )}
                {isFailed && (
                  <span className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--non-compliant)" }}>
                    <AlertCircle className="w-3 h-3" /> Failed
                  </span>
                )}
              </div>

              <RaceTrack
                completed={jobStatus?.agents_completed || []}
                current={jobStatus?.current_agent}
                progress={jobStatus?.progress || 0}
                status={jobStatus?.status}
                results={computeRaceResults(jobStatus?.report, jobStatus?.status)}
                score={jobStatus?.report?.summary?.compliance_score}
              />

              <div className="mt-3 flex justify-between text-[11px]" style={{ color: "var(--text-muted)" }}>
                <span>{jobStatus?.progress || 0}% complete</span>
                {isProcessing && jobStatus?.current_agent && (
                  <span style={{ color: "var(--accent)" }}>{jobStatus.current_agent} working…</span>
                )}
              </div>
            </section>

              {isFailed && (
                <div
                  className="p-4 rounded-xl"
                  style={{ background: "var(--non-compliant-bg)", border: "1px solid rgba(185,28,28,0.25)" }}
                >
                  <p className="text-[13px] font-semibold mb-1" style={{ color: "var(--non-compliant)" }}>
                    Processing failed
                  </p>
                  <p className="text-[12px]" style={{ color: "var(--text-secondary)" }}>
                    {jobStatus?.error || "Unknown error"}
                  </p>
                  <button
                    onClick={handleReset}
                    className="mt-3 text-[12px] font-medium underline"
                    style={{ color: "var(--non-compliant)" }}
                  >
                    Try again
                  </button>
                </div>
              )}

              {isCompleted && (
                <button
                  onClick={() => setActiveTab("report")}
                  className="w-full py-3 rounded-lg font-semibold text-[13px] flex items-center justify-center gap-2 btn-primary"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  <Activity className="w-4 h-4" />
                  View compliance report
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Agent logs — collapsible, secondary to the race track */}
              <section>
                <button
                  onClick={() => setLogsOpen((o) => !o)}
                  className="flex items-center gap-2 mb-3 text-[11px] font-semibold tracking-[0.18em] uppercase"
                  style={{ color: "var(--text-muted)" }}
                >
                  <ChevronRight className="w-3.5 h-3.5 transition-transform" style={{ transform: logsOpen ? "rotate(90deg)" : "none" }} />
                  Agent logs
                  {isProcessing && (
                    <span className="text-[10px] font-semibold tracking-wider px-1.5 py-0.5 rounded-md" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
                      LIVE
                    </span>
                  )}
                </button>
                {logsOpen && (
                  <AgentLogs logs={logs} isProcessing={isProcessing} currentAgent={jobStatus?.current_agent} />
                )}
              </section>
            </div>
        )}

        {/* ── REPORT TAB ── */}
        {activeTab === "report" && jobStatus?.report && (
          <ComplianceReport
            report={jobStatus.report}
            jobId={jobId!}
            filename={uploadedFile?.name}
          />
        )}
      </main>
        </div>
      </div>

      {/* ── Sticky bottom utility bar — secondary controls live here so the
          header can stay sparse like the marketing nav. Hidden behind the
          report so it never overlaps the long PDF view. */}
      <BottomBar
        isAuthed={isAuthed}
        profile={profile}
        onSignOut={handleSignOut}
        onNav={(path) => router.push(path)}
      />
    </div>
  );
}

// ─── BottomBar ──────────────────────────────────────────────────────
function BottomBar({
  isAuthed,
  profile,
  onSignOut,
  onNav,
}: {
  isAuthed: boolean | null;
  profile: UserProfile | null;
  onSignOut: () => void;
  onNav: (path: string) => void;
}) {
  return (
    <div
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3 py-2 rounded-full shadow-premium"
      style={{
        background: "rgba(255, 255, 255, 0.92)",
        backdropFilter: "blur(8px)",
        border: "1px solid var(--border)",
      }}
    >
      <button
        onClick={() => onNav("/billing")}
        className="text-[12px] font-medium px-3 py-1.5 rounded-md hover:opacity-70 transition-opacity duration-150"
        style={{ color: "var(--text-secondary)" }}
      >
        Pricing
      </button>

      {isAuthed === true && (
        <>
          <span className="w-px h-4" style={{ background: "var(--border)" }} />
          <button
            onClick={() => onNav("/account")}
            className="text-[12px] font-medium px-3 py-1.5 rounded-md hover:opacity-70 transition-opacity duration-150"
            style={{ color: "var(--text-secondary)" }}
          >
            Account
          </button>
        </>
      )}

      {profile && (
        <>
          <span className="w-px h-4" style={{ background: "var(--border)" }} />
          <button
            onClick={() => onNav("/billing")}
            className="text-[12px] font-medium px-3 py-1.5 rounded-md hover:opacity-70 transition-opacity duration-150"
            style={{ color: "var(--text-primary)" }}
            title={`${profile.email} — manage plan`}
          >
            {profile.is_admin ? (
              <span style={{ color: "var(--accent)" }}>Admin · Unlimited</span>
            ) : (
              <>
                {profile.plan_tier && profile.plan_tier !== "free" ? (
                  <span style={{ color: "var(--accent)" }}>
                    {profile.plan_tier.charAt(0).toUpperCase() + profile.plan_tier.slice(1)}
                    {" · "}
                  </span>
                ) : null}
                {profile.credits_remaining}
                {" "}
                {profile.credits_remaining === 1 ? "credit" : "credits"}
              </>
            )}
          </button>

          {!profile.is_admin && (!profile.plan_tier || profile.plan_tier === "free") && (
            <button
              onClick={() => onNav("/billing")}
              className="text-[12px] font-semibold px-3 py-1.5 rounded-md btn-primary"
            >
              Upgrade
            </button>
          )}

          <span className="w-px h-4" style={{ background: "var(--border)" }} />
          <button
            onClick={onSignOut}
            className="text-[12px] font-medium px-3 py-1.5 rounded-md hover:opacity-70 transition-opacity duration-150"
            style={{ color: "var(--text-muted)" }}
          >
            Sign out
          </button>
        </>
      )}

      {isAuthed === false && (
        <>
          <span className="w-px h-4" style={{ background: "var(--border)" }} />
          <button
            onClick={() => onNav("/login?redirect=/dashboard")}
            className="text-[12px] font-medium px-3 py-1.5 rounded-md hover:opacity-70 transition-opacity duration-150"
            style={{ color: "var(--text-secondary)" }}
          >
            Sign in
          </button>
          <button
            onClick={() => onNav("/signup?redirect=/dashboard")}
            className="text-[12px] font-semibold px-3 py-1.5 rounded-md btn-primary"
          >
            Get started — free
          </button>
        </>
      )}
    </div>
  );
}

