"use client";

import { useEffect, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";
import { uploadPlan, getJobStatus, createWebSocket, getExportUrl, getMe } from "@/lib/api";
import type { AgentLog, UserProfile } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";
import FileUpload from "@/components/FileUpload";
import AgentLogs from "@/components/AgentLogs";
import ComplianceReport from "@/components/ComplianceReport";
import Reveal from "@/components/Reveal";
import {
  Building2, Cpu, FileCheck, ChevronRight,
  Activity, CheckCircle2, AlertCircle, Clock, RotateCcw,
  Search, BookOpen, Landmark, Flame, Zap, Droplets, Wind,
  Accessibility, Leaf, Compass, Construction, Trees, ArrowRight, ArrowUpRight,
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
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string>("");
  const router = useRouter();
  const [isAuthed, setIsAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    const sb = createClient();
    sb.auth.getSession().then(({ data: { session } }) => {
      setIsAuthed(!!session);
    }).catch(() => setIsAuthed(false));
  }, []);

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

  const connectWebSocket = (id: string) => {
    try {
      const ws = createWebSocket(id);
      wsRef.current = ws;
      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => setWsConnected(false);
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "log" && msg.data) addLog(msg.data as AgentLog);
          if (msg.type === "status" && msg.data) {
            setJobStatus((prev) => prev ? { ...prev, ...msg.data } : msg.data);
          }
          if (msg.type === "completed" || msg.type === "failed") {
            getJobStatus(id).then((status) => {
              setJobStatus(status);
              setLogs(status.logs);
              if (status.status === "completed") setActiveTab("report");
            });
          }
        } catch {}
      };
    } catch {
      startPolling(id);
    }
  };

  const startPolling = (id: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const status = await getJobStatus(id);
        setJobStatus(status);
        setLogs(status.logs);
        if (status.status === "completed" || status.status === "failed") {
          clearInterval(pollRef.current!);
          if (status.status === "completed") setActiveTab("report");
        }
      } catch {}
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
      connectWebSocket(result.job_id);
      startPolling(result.job_id);
    } catch (err) {
      alert(`Upload failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  };

  const handleReset = () => {
    wsRef.current?.close();
    if (pollRef.current) clearInterval(pollRef.current);
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
            className="flex items-center gap-1 flex-shrink-0 rounded-lg hover:opacity-80 transition-opacity duration-150"
            aria-label="Go to home page"
          >
            <span
              className="font-semibold text-[18px] tracking-[-0.025em]"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
            >
              Up2Code
            </span>
            <ArrowUpRight
              className="w-3.5 h-3.5"
              strokeWidth={2.5}
              style={{ color: "var(--text-primary)" }}
            />
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
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
            <div className="lg:col-span-3">
              <AgentLogs logs={logs} isProcessing={isProcessing} currentAgent={jobStatus?.current_agent} />
            </div>

            <div className="lg:col-span-2 space-y-8">
              {/* Progress — flat surface. */}
              <section>
                <div className="flex items-center justify-between mb-3">
                  <h3
                    className="text-[11px] font-semibold tracking-[0.18em] uppercase"
                    style={{ color: "var(--text-muted)" }}
                  >
                    Progress
                  </h3>
                  {isProcessing && (
                    <span className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--accent)" }}>
                      <Clock className="w-3 h-3" />
                      Running
                    </span>
                  )}
                  {isCompleted && (
                    <span className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--compliant)" }}>
                      <CheckCircle2 className="w-3 h-3" />
                      Done
                    </span>
                  )}
                  {isFailed && (
                    <span className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--non-compliant)" }}>
                      <AlertCircle className="w-3 h-3" />
                      Failed
                    </span>
                  )}
                </div>
                <div
                  className="h-1.5 rounded-md overflow-hidden mb-2"
                  style={{ background: "var(--bg-elevated)" }}
                >
                  <div
                    className={`h-full rounded-md transition-all duration-500 ${isProcessing ? "progress-bar-active" : ""}`}
                    style={{
                      width: `${jobStatus?.progress || 0}%`,
                      background: isProcessing
                        ? undefined
                        : isCompleted
                          ? "var(--compliant)"
                          : isFailed
                            ? "var(--non-compliant)"
                            : "var(--accent)",
                    }}
                  />
                </div>
                <div className="flex justify-between text-[11px]" style={{ color: "var(--text-muted)" }}>
                  <span>{jobStatus?.progress || 0}% complete</span>
                  {jobStatus?.current_agent && (
                    <span style={{ color: "var(--accent)" }}>{jobStatus.current_agent} working…</span>
                  )}
                </div>
              </section>

              {/* Agents — flat list, no per-row card chrome. */}
              <section>
                <h3
                  className="text-[11px] font-semibold tracking-[0.18em] uppercase mb-3"
                  style={{ color: "var(--text-muted)" }}
                >
                  Pipeline
                </h3>
                <div className="space-y-1.5">
                  {AGENTS.map((agent) => {
                    const isDone = (jobStatus?.agents_completed || []).includes(agent.id);
                    const isActive = jobStatus?.current_agent === agent.id;
                    const fg = isDone
                      ? "var(--compliant)"
                      : isActive
                      ? "var(--accent)"
                      : "var(--text-secondary)";
                    return (
                      <div
                        key={agent.id}
                        className={`flex items-center gap-3 p-3 rounded-xl ${isActive ? "agent-active" : ""}`}
                        style={{
                          background: isDone
                            ? "var(--compliant-bg)"
                            : isActive
                            ? "var(--accent-soft)"
                            : "transparent",
                        }}
                      >
                        <agent.Icon className="w-4 h-4" style={{ color: fg }} />
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] font-medium" style={{ color: fg }}>
                            {agent.label}
                          </div>
                          <div className="text-[11px] truncate" style={{ color: "var(--text-muted)" }}>
                            {agent.description}
                          </div>
                        </div>
                        {isDone && <CheckCircle2 className="w-4 h-4 flex-shrink-0" style={{ color: "var(--compliant)" }} />}
                        {isActive && (
                          <div
                            className="w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin flex-shrink-0"
                            style={{ color: "var(--accent)" }}
                          />
                        )}
                      </div>
                    );
                  })}
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
            </div>
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

