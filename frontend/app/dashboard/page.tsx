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
  Accessibility, Leaf, Compass, Construction, Trees,
} from "lucide-react";

// ─── Agent Step Indicator ───────────────────────────────────────────
// Pipeline shows 3 stages — but Stage 3 fans out into 10 parallel department reviewers.
const DEPARTMENT_AGENTS = [
  "Building & Safety", "Fire Department", "Electrical Inspector", "Plumbing Inspector",
  "Mechanical Inspector", "Accessibility (ADA / CBC 11B)", "Energy & Green Building",
  "Planning & Zoning", "Public Works", "Environmental",
];

const AGENTS = [
  {
    id: "Surveyor",
    label: "Surveyor",
    Icon: Search,
    description: "Identifies jurisdiction from title block",
  },
  {
    id: "Librarian",
    label: "Librarian",
    Icon: BookOpen,
    description: "Retrieves applicable building codes",
  },
  {
    id: "Departments",
    label: "10 Departments",
    Icon: Landmark,
    description: "Building Safety, Fire, Electrical, Plumbing, Mechanical, ADA, Energy, Zoning, Public Works, Environmental",
    isGroup: true,
    members: DEPARTMENT_AGENTS,
  },
];

function AgentPipeline({
  completed,
  current,
}: {
  completed: string[];
  current?: string | null;
}) {
  return (
    <div className="flex items-center gap-1 sm:gap-2">
      {AGENTS.map((agent, i) => {
        // For the Departments group: done = all members complete; active = any member in progress
        const isGroup = !!(agent as { isGroup?: boolean }).isGroup;
        const members = (agent as { members?: string[] }).members || [];
        const doneCount = isGroup ? members.filter((m) => completed.includes(m)).length : 0;
        const isDone = isGroup
          ? doneCount === members.length && members.length > 0
          : completed.includes(agent.id);
        const isActive = isGroup
          ? !isDone && members.some((m) => m === current || completed.includes(m))
          : current === agent.id;
        const isPending = !isDone && !isActive;

        return (
          <div key={agent.id} className="flex items-center gap-1 sm:gap-2">
            <div
              className={`relative flex items-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-all duration-300
                ${isDone ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" : ""}
                ${isActive ? "bg-amber-500/10 border-amber-500/40 text-amber-200 agent-active" : ""}
                ${isPending ? "bg-surface-800/50 border-white/5 text-[var(--text-muted)]" : ""}
              `}
            >
              <agent.Icon className="w-4 h-4" />
              <span className="hidden sm:block">
                {agent.label}
                {isGroup && isActive && (
                  <span className="ml-1.5 opacity-70 text-xs">
                    ({doneCount}/{members.length})
                  </span>
                )}
              </span>
              {isDone && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
              {isActive && (
                <div className="w-3.5 h-3.5 rounded-full border-2 border-amber-300 border-t-transparent animate-spin" />
              )}
            </div>
            {i < AGENTS.length - 1 && (
              <ChevronRight
                className={`w-4 h-4 flex-shrink-0 transition-colors
                  ${isDone ? "text-emerald-500/50" : "text-white/10"}`}
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
  // null = checking, true/false = known. Lets us distinguish "loading" from
  // "definitely not signed in" so the header doesn't flash the wrong state.
  const [isAuthed, setIsAuthed] = useState<boolean | null>(null);

  // On mount: figure out whether the visitor is signed in. Dashboard is the
  // PUBLIC landing page — unauth visitors get the same UI, just prompted to
  // sign in when they try to upload.
  useEffect(() => {
    const sb = createClient();
    sb.auth.getSession().then(({ data: { session } }) => {
      setIsAuthed(!!session);
    }).catch(() => setIsAuthed(false));
  }, []);

  // Load profile only when we know the user is signed in. Skip the wasted
  // 401 round-trip for anonymous landing-page visitors.
  useEffect(() => {
    if (isAuthed) {
      getMe().then(setProfile).catch(() => setProfile(null));
    }
  }, [jobStatus, isAuthed]); // refresh credits after a job

  const handleSignOut = async () => {
    const sb = createClient();
    await sb.auth.signOut();
    router.push("/login");
    router.refresh();
  };

  // Cleanup on unmount
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
          if (msg.type === "log" && msg.data) {
            addLog(msg.data as AgentLog);
          }
          if (msg.type === "status" && msg.data) {
            setJobStatus((prev) => prev ? { ...prev, ...msg.data } : msg.data);
          }
          if (msg.type === "completed" || msg.type === "failed") {
            // Fetch final full status
            getJobStatus(id).then((status) => {
              setJobStatus(status);
              setLogs(status.logs);
              if (status.status === "completed") {
                setActiveTab("report");
              }
            });
          }
        } catch {}
      };
    } catch {
      // WS failed — fall back to polling
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
          if (status.status === "completed") {
            setActiveTab("report");
          }
        }
      } catch {}
    }, 1000);
  };

  const handleUpload = async (file: File) => {
    // Only ACTION that requires an account: actually running a review.
    // Browsing the dashboard, viewing the demo, and reading docs are all free.
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

      // Fetch initial status
      const status = await getJobStatus(result.job_id);
      setJobStatus(status);

      // Connect WS + polling
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
    <div className="min-h-screen bg-grid" style={{ background: "var(--bg)" }}>
      {/* ── Header ── */}
      <header
        className="sticky top-0 z-50 border-b backdrop-blur"
        style={{
          background: "rgba(255,255,255,0.85)",
          borderColor: "var(--border)",
        }}
      >
        <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-4">
          {/* Logo — clicks back to the marketing home page */}
          <button
            onClick={() => router.push("/")}
            className="flex items-center gap-3 flex-shrink-0 rounded-lg transition-opacity hover:opacity-80"
            aria-label="Go to home page"
          >
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ background: "#0B0E14" }}
            >
              <Building2 className="w-4.5 h-4.5 text-white" />
            </div>
            <span
              className="font-bold text-sm tracking-wide"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
            >
              Up2Code AI
            </span>
          </button>

          {/* Pipeline (center, hidden when not active) */}
          {(isProcessing || isCompleted) && (
            <div className="hidden md:flex flex-1 justify-center">
              <AgentPipeline
                completed={jobStatus?.agents_completed || []}
                current={jobStatus?.current_agent}
              />
            </div>
          )}

          {/* Right controls */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              onClick={() => router.push("/billing")}
              className="text-xs font-medium px-3 py-1.5 rounded-lg transition-colors hover:underline"
              style={{ color: "var(--text-secondary)" }}
            >
              Pricing
            </button>
            {/* Logged-in visitors see Account. Anonymous landing-page visitors
                see Sign in + Get started instead — converting the dashboard
                from a gated app into the marketing surface. */}
            {isAuthed === true && (
              <button
                onClick={() => router.push("/account")}
                className="text-xs font-medium px-3 py-1.5 rounded-lg transition-colors hover:underline"
                style={{ color: "var(--text-secondary)" }}
              >
                Account
              </button>
            )}
            {isAuthed === false && (
              <>
                <button
                  onClick={() => router.push("/login?redirect=/dashboard")}
                  className="text-xs font-medium px-3 py-1.5 rounded-lg transition-colors hover:underline"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Sign in
                </button>
                <button
                  onClick={() => router.push("/signup?redirect=/dashboard")}
                  className="text-xs font-medium px-3 py-1.5 rounded-lg"
                  style={{ background: "#0B0E14", color: "#fff" }}
                >
                  Get started — free
                </button>
              </>
            )}
            {wsConnected && (
              <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Live
              </div>
            )}
            {profile && (
              <div className="flex items-center gap-3 text-xs">
                <button
                  onClick={() => router.push("/billing")}
                  className="px-2 py-1 rounded-md font-medium transition-colors"
                  style={{
                    color: "var(--text-primary)",
                    border: "1px solid var(--border)",
                    background: "var(--bg-card)",
                  }}
                  title={`${profile.email} — manage plan`}
                >
                  {profile.is_admin ? (
                    <span style={{ color: "var(--accent-bright)" }}>Admin · Unlimited</span>
                  ) : (
                    <>
                      {profile.plan_tier && profile.plan_tier !== "free" ? (
                        <span style={{ color: "var(--accent-bright)" }}>
                          {profile.plan_tier.charAt(0).toUpperCase() + profile.plan_tier.slice(1)} ·{" "}
                        </span>
                      ) : null}
                      {profile.credits_remaining} {profile.credits_remaining === 1 ? "credit" : "credits"}
                    </>
                  )}
                </button>
                {!profile.is_admin && (!profile.plan_tier || profile.plan_tier === "free") && (
                  <button
                    onClick={() => router.push("/billing")}
                    className="px-3 py-1 rounded-md font-medium transition-all"
                    style={{
                      background: "#0B0E14",
                      color: "#fff",
                    }}
                  >
                    Upgrade
                  </button>
                )}
                <button
                  onClick={handleSignOut}
                  className="text-xs font-medium hover:underline"
                  style={{ color: "var(--text-muted)" }}
                >
                  Sign out
                </button>
              </div>
            )}
            {jobId && (
              <button
                onClick={handleReset}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
                style={{
                  color: "var(--text-secondary)",
                  border: "1px solid var(--border)",
                  background: "var(--bg-card)",
                }}
              >
                <RotateCcw className="w-3.5 h-3.5" />
                New Check
              </button>
            )}
          </div>
        </div>
      </header>

      {/* ── Tab Bar ── */}
      {jobId && (
        <div
          className="border-b"
          style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
        >
          <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 flex gap-1 overflow-x-auto">
            {[
              { id: "upload", label: "Upload", icon: <FileCheck className="w-3.5 h-3.5" /> },
              {
                id: "processing",
                label: "Agent Logs",
                icon: <Cpu className="w-3.5 h-3.5" />,
                badge: isProcessing ? "LIVE" : undefined,
              },
              {
                id: "report",
                label: "Compliance Report",
                icon: <Activity className="w-3.5 h-3.5" />,
                disabled: !isCompleted,
              },
            ].map((tab) => (
              <button
                key={tab.id}
                disabled={tab.disabled}
                onClick={() => !tab.disabled && setActiveTab(tab.id as "upload" | "processing" | "report")}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-all whitespace-nowrap
                  ${activeTab === tab.id
                    ? "border-amber-500 text-amber-200"
                    : tab.disabled
                      ? "border-transparent text-[var(--text-muted)] cursor-not-allowed"
                      : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  }`}
              >
                {tab.icon}
                {tab.label}
                {tab.badge && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-200 border border-amber-500/30">
                    {tab.badge}
                  </span>
                )}
                {tab.id === "report" && isCompleted && (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Content ── */}
      <main className="max-w-screen-2xl mx-auto px-4 sm:px-6 py-6">

        {/* ── UPLOAD TAB ── */}
        {(activeTab === "upload" || !jobId) && (
          <div className="max-w-screen-2xl mx-auto">
            {/* Hero */}
            <div className="text-center mb-10 pt-6">
              <div className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded-full mb-6"
                style={{
                  background: "rgba(79, 126, 255, 0.08)",
                  border: "1px solid rgba(79, 126, 255, 0.2)",
                  color: "var(--accent-bright)"
                }}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-amber-300 animate-pulse" />
                12-Agent AI Workflow · IBC · NFPA · NEC · IPC · IMC · ADA · CALGreen · Title 24
              </div>
              <h1
                className="text-4xl sm:text-5xl font-bold mb-4 leading-tight"
                style={{ fontFamily: "var(--font-display)" }}
              >
                <span className="text-gradient">Automated</span>
                <br />
                <span style={{ color: "var(--text-primary)" }}>Plan Compliance</span>
              </h1>
              <p className="text-base" style={{ color: "var(--text-secondary)" }}>
                Upload a PDF plan set. <strong style={{ color: "var(--text-primary)" }}>12 specialist AI agents</strong> identify
                your jurisdiction and audit it against every code chapter a real city plan check runs.
              </p>
            </div>

            <FileUpload onUpload={handleUpload} isUploading={isUploading} uploadProgress={uploadProgress} uploadStatus={uploadStatus} />

            {/* Pipeline overview — fade-up reveal with a slight stagger so
                the cards feel sequenced rather than slamming in together. */}
            <div className="grid grid-cols-2 gap-3 mt-8">
              <Reveal delay={0.05} className="p-4 rounded-xl"
                   style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
                <Search className="w-6 h-6 mb-2" style={{ color: "var(--accent-bright)" }} />
                <div className="text-sm font-semibold mb-1"
                     style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  Surveyor
                </div>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Reads title blocks and identifies AHJ, occupancy, construction type
                </div>
              </Reveal>
              <Reveal delay={0.12} className="p-4 rounded-xl"
                   style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
                <BookOpen className="w-6 h-6 mb-2" style={{ color: "var(--accent-bright)" }} />
                <div className="text-sm font-semibold mb-1"
                     style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  Librarian
                </div>
                <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Pulls IBC, NFPA, NEC, IPC, IMC, ADA and local amendments
                </div>
              </Reveal>
            </div>

            {/* Department reviewers — outer card and inner chips both Reveal
                so they cascade in. The chip stagger feels appropriate for a
                10-element grid; ~30ms between each lands the last one ~300ms
                after the first. */}
            <Reveal delay={0.2} className="mt-3 p-4 rounded-xl"
                 style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 text-sm font-semibold"
                     style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  <Landmark className="w-4 h-4" />
                  10 Department Reviewers
                  <span className="font-normal" style={{ color: "var(--text-muted)" }}>· run in parallel</span>
                </div>
                <div className="text-xs" style={{ color: "var(--accent-bright)" }}>
                  Like a real city plan check
                </div>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                {[
                  { Icon: Building2, label: "Building & Safety" },
                  { Icon: Flame, label: "Fire" },
                  { Icon: Zap, label: "Electrical" },
                  { Icon: Droplets, label: "Plumbing" },
                  { Icon: Wind, label: "Mechanical" },
                  { Icon: Accessibility, label: "Accessibility" },
                  { Icon: Leaf, label: "Energy" },
                  { Icon: Compass, label: "Zoning" },
                  { Icon: Construction, label: "Public Works" },
                  { Icon: Trees, label: "Environmental" },
                ].map((d, i) => (
                  <Reveal key={d.label} delay={0.25 + i * 0.03} y={6}
                       className="flex items-center gap-2 px-2.5 py-2 rounded-md"
                       style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
                    <d.Icon className="w-3.5 h-3.5" style={{ color: "var(--text-secondary)" }} />
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{d.label}</span>
                  </Reveal>
                ))}
              </div>
            </Reveal>

            {/* Demo: what a finished review looks like */}
            <ExampleReview />
          </div>
        )}

        {/* ── PROCESSING TAB ── */}
        {activeTab === "processing" && jobId && (
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
            {/* Logs panel */}
            <div className="lg:col-span-3">
              <AgentLogs logs={logs} isProcessing={isProcessing} currentAgent={jobStatus?.current_agent} />
            </div>

            {/* Status sidebar */}
            <div className="lg:col-span-2 space-y-4">
              {/* Progress card */}
              <div
                className="p-5 rounded-2xl"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
              >
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                    Processing Progress
                  </h3>
                  {isProcessing && (
                    <span className="flex items-center gap-1.5 text-xs text-amber-300">
                      <Clock className="w-3 h-3" />
                      Running
                    </span>
                  )}
                  {isCompleted && (
                    <span className="flex items-center gap-1.5 text-xs text-emerald-400">
                      <CheckCircle2 className="w-3 h-3" />
                      Done
                    </span>
                  )}
                  {isFailed && (
                    <span className="flex items-center gap-1.5 text-xs text-red-400">
                      <AlertCircle className="w-3 h-3" />
                      Failed
                    </span>
                  )}
                </div>

                {/* Progress bar */}
                <div
                  className="h-2 rounded-full overflow-hidden mb-3"
                  style={{ background: "var(--bg-elevated)" }}
                >
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${isProcessing ? "progress-bar-active" : ""}`}
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
                <div className="flex justify-between text-xs" style={{ color: "var(--text-muted)" }}>
                  <span>{jobStatus?.progress || 0}% complete</span>
                  {jobStatus?.current_agent && (
                    <span className="text-amber-300">{jobStatus.current_agent} working…</span>
                  )}
                </div>
              </div>

              {/* Agents status */}
              <div
                className="p-5 rounded-2xl"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
              >
                <h3 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
                  Agent Pipeline
                </h3>
                <div className="space-y-3">
                  {AGENTS.map((agent) => {
                    const isDone = (jobStatus?.agents_completed || []).includes(agent.id);
                    const isActive = jobStatus?.current_agent === agent.id;
                    return (
                      <div
                        key={agent.id}
                        className={`flex items-center gap-3 p-3 rounded-xl transition-all
                          ${isDone ? "opacity-80" : isActive ? "opacity-100" : "opacity-40"}`}
                        style={{
                          background: isDone
                            ? "var(--compliant-bg)"
                            : isActive
                              ? "rgba(79, 126, 255, 0.06)"
                              : "transparent",
                          border: `1px solid ${isDone ? "rgba(16,185,129,0.2)" : isActive ? "rgba(79,126,255,0.2)" : "transparent"}`,
                        }}
                      >
                        <agent.Icon className="w-5 h-5" />
                        <div className="flex-1 min-w-0">
                          <div
                            className="text-sm font-medium"
                            style={{ color: isDone ? "#34d399" : isActive ? "#93c5fd" : "var(--text-secondary)" }}
                          >
                            {agent.label}
                          </div>
                          <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                            {agent.description}
                          </div>
                        </div>
                        {isDone && <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />}
                        {isActive && (
                          <div className="w-4 h-4 rounded-full border-2 border-amber-300 border-t-transparent animate-spin flex-shrink-0" />
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Error state */}
              {isFailed && (
                <div
                  className="p-4 rounded-xl"
                  style={{ background: "var(--non-compliant-bg)", border: "1px solid rgba(239,68,68,0.3)" }}
                >
                  <p className="text-sm text-red-400 font-medium mb-1">Processing failed</p>
                  <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {jobStatus?.error || "Unknown error"}
                  </p>
                  <button
                    onClick={handleReset}
                    className="mt-3 text-xs text-red-400 underline"
                  >
                    Try again
                  </button>
                </div>
              )}

              {/* View Report button */}
              {isCompleted && (
                <button
                  onClick={() => setActiveTab("report")}
                  className="w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all glow-blue"
                  style={{
                    background: "linear-gradient(135deg, var(--accent-soft), var(--accent))",
                    color: "white",
                  }}
                >
                  <Activity className="w-4 h-4" />
                  View Compliance Report
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
    </div>
  );
}

// ─── Example Review (demo block on upload tab) ───────────────────────
function ExampleReview() {
  const EXAMPLES: Array<{
    department: string;
    Icon: React.ElementType;
    severity: "critical" | "high" | "medium";
    section: string;
    text: string;
  }> = [
    {
      department: "Fire",
      Icon: Flame,
      severity: "critical",
      section: "IFC 903.2",
      text: "New SFD rebuild requires NFPA 13D sprinklers per CRC R313.2. Title sheet does not call out sprinkler standard.",
    },
    {
      department: "Building & Safety",
      Icon: Building2,
      severity: "high",
      section: "IBC 503",
      text: "Construction type and height/area not documented. Allowable height/area cannot be verified.",
    },
    {
      department: "Environmental",
      Icon: Trees,
      severity: "critical",
      section: "CBC 7A",
      text: "Project is in a Very High Fire Hazard Severity Zone — ignition-resistant construction is required.",
    },
    {
      department: "Energy & Green",
      Icon: Leaf,
      severity: "high",
      section: "Title 24",
      text: "CA Climate Zone 9 — envelope U-values and PV solar requirement not addressed in submitted plans.",
    },
  ];
  const SEV_COLORS: Record<string, string> = {
    critical: "var(--non-compliant)",
    high: "#B45309",
    medium: "var(--accent)",
  };

  return (
    <div className="mt-10">
      <div className="flex items-center justify-between mb-3 px-1">
        <h2
          className="text-sm font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-muted)", fontFamily: "var(--font-display)" }}
        >
          See an example review
        </h2>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          Real output, redacted address
        </span>
      </div>

      <div
        className="rounded-2xl p-6"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        {/* Project header */}
        <div className="flex items-start justify-between flex-wrap gap-3 mb-5 pb-5"
             style={{ borderBottom: "1px solid var(--border)" }}>
          <div>
            <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>
              Example project
            </div>
            <div className="text-lg font-semibold"
                 style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}>
              Single-family rebuild · Altadena, CA
            </div>
            <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
              R-3 occupancy · 37 pages · Code: 2022 California Building Code
            </div>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold" style={{ color: "var(--non-compliant)" }}>
              4%
            </div>
            <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              compliance score
            </div>
          </div>
        </div>

        {/* Tally */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: "compliant", value: 2, color: "var(--compliant)" },
            { label: "needs review", value: 51, color: "var(--needs-review)" },
            { label: "critical", value: 5, color: "var(--non-compliant)" },
            { label: "high", value: 19, color: "#B45309" },
          ].map((t) => (
            <div key={t.label}
                 className="rounded-lg p-3 text-center"
                 style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
              <div className="text-xl font-bold" style={{ color: t.color, fontFamily: "var(--font-display)" }}>
                {t.value}
              </div>
              <div className="text-[10px] uppercase tracking-wider mt-0.5"
                   style={{ color: "var(--text-muted)" }}>
                {t.label}
              </div>
            </div>
          ))}
        </div>

        {/* Top findings */}
        <div className="space-y-2">
          {EXAMPLES.map((f, i) => (
            <div key={i}
                 className="flex items-start gap-3 p-3 rounded-lg"
                 style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
              <div className="w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0"
                   style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
                <f.Icon className="w-4 h-4" style={{ color: "var(--text-secondary)" }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-xs font-semibold"
                        style={{ color: "var(--text-primary)" }}>
                    {f.department}
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                        style={{
                          background: "rgba(184, 148, 31, 0.10)",
                          color: "var(--accent)",
                          border: "1px solid rgba(184, 148, 31, 0.20)",
                        }}>
                    {f.section}
                  </span>
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded uppercase tracking-wider"
                        style={{
                          color: SEV_COLORS[f.severity],
                          background: `${SEV_COLORS[f.severity]}15`,
                          border: `1px solid ${SEV_COLORS[f.severity]}30`,
                        }}>
                    {f.severity}
                  </span>
                </div>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{f.text}</p>
              </div>
            </div>
          ))}
        </div>

        <p className="text-xs mt-5 text-center"
           style={{ color: "var(--text-muted)" }}>
          Every real review checks ~68 code requirements across all 12 agents and returns full
          recommendations on each finding.
        </p>
      </div>
    </div>
  );
}
