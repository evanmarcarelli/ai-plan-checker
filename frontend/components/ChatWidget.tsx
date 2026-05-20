"use client";

// Floating AI-assistant panel pinned to the bottom-right of a report page.
//
// Scope: clarifying questions only ("what does IBC 1011.5.2 require?",
// "why was this flagged?"). The backend grounds every answer in the RAG
// corpus and returns citations, which we render as expandable pills.
//
// Works for owners (JWT) and guests (shareToken) — same component.
import { useEffect, useRef, useState } from "react";
import { Bot, ChevronDown, Send, Sparkles, X } from "lucide-react";
import { fetchChatHistory, postChatQuestion, type ChatMessage } from "@/lib/api";

const SUGGESTED = [
  "What does this report's lowest-scoring section mean?",
  "Explain the difference between AFCI and GFCI.",
  "What is a defensible space requirement?",
];

export function ChatWidget({
  jobId,
  shareToken,
  guestName,
  findingRef,
}: {
  jobId: string;
  shareToken?: string;
  guestName?: string;
  findingRef?: string;
}) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedHistory, setLoadedHistory] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && !loadedHistory) {
      fetchChatHistory(jobId, { shareToken })
        .then(({ messages }) => setMessages(messages))
        .catch(() => {/* history is best-effort */})
        .finally(() => setLoadedHistory(true));
    }
  }, [open, loadedHistory, jobId, shareToken]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setError(null);
    setBusy(true);
    // Optimistic: show the user message immediately
    const optimistic: ChatMessage = {
      id: `tmp-${Date.now()}`,
      role: "user",
      content: q,
      author_display: guestName || "You",
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, optimistic]);
    setDraft("");
    try {
      const res = await postChatQuestion(jobId, q, { shareToken, guestName, findingRef });
      setMessages((m) => [
        ...m,
        {
          id: res.message_id,
          role: "assistant",
          content: res.reply,
          citations: res.citations,
          author_display: "Up2Code AI",
          created_at: new Date().toISOString(),
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 px-4 py-3 rounded-full shadow-lg"
        style={{ background: "#0B0E14", color: "#fff" }}
      >
        <Sparkles className="w-4 h-4" />
        <span className="text-sm font-medium">Ask the AI assistant</span>
      </button>
    );
  }

  return (
    <div
      className="fixed bottom-5 right-5 z-40 flex flex-col rounded-xl shadow-2xl"
      style={{
        width: "min(420px, calc(100vw - 2.5rem))",
        height: "min(560px, calc(100vh - 2.5rem))",
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="flex items-center gap-2">
          <div
            className="inline-flex items-center justify-center w-7 h-7 rounded-lg"
            style={{ background: "#0B0E14" }}
          >
            <Bot className="w-4 h-4 text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Up2Code Assistant
            </div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>
              Code clarifications · grounded in cited sections
            </div>
          </div>
        </div>
        <button onClick={() => setOpen(false)} aria-label="Close" style={{ color: "var(--text-muted)" }}>
          <ChevronDown className="w-5 h-5" />
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Ask me a quick clarifying question about this report or building
              code in general. I'll quote the relevant code sections.
            </p>
            <div className="space-y-1.5">
              {SUGGESTED.map((s) => (
                <button
                  key={s}
                  onClick={() => ask(s)}
                  className="block w-full text-left text-xs px-3 py-2 rounded-lg"
                  style={{
                    background: "var(--bg-elevated)",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <ChatBubble key={m.id} message={m} />
        ))}

        {busy && (
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            Up2Code AI is thinking…
          </div>
        )}
        {error && (
          <p className="text-xs px-3 py-2 rounded-lg"
             style={{ background: "var(--non-compliant-bg)", color: "var(--non-compliant)" }}>
            {error}
          </p>
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void ask(draft);
        }}
        className="p-3 border-t flex items-end gap-2"
        style={{ borderColor: "var(--border)" }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(draft);
            }
          }}
          placeholder="Ask a clarifying question…"
          rows={1}
          className="flex-1 px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
            maxHeight: "120px",
          }}
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="p-2 rounded-lg disabled:opacity-50"
          style={{ background: "#0B0E14", color: "#fff" }}
          aria-label="Send"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>

      <p className="px-4 pb-3 text-[10px] leading-tight" style={{ color: "var(--text-muted)" }}>
        AI guidance is preliminary. Verify with your local AHJ before relying on
        it for permit purposes.
      </p>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const [showCites, setShowCites] = useState(false);
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className="max-w-[85%] rounded-xl px-3 py-2"
        style={{
          background: isUser ? "#0B0E14" : "var(--bg-elevated)",
          color: isUser ? "#fff" : "var(--text-primary)",
          border: isUser ? "none" : "1px solid var(--border)",
        }}
      >
        {!isUser && (
          <div className="text-[10px] font-medium mb-1" style={{ color: "var(--text-muted)" }}>
            {message.author_display || "Up2Code AI"}
          </div>
        )}
        <p className="text-sm whitespace-pre-wrap leading-relaxed">{message.content}</p>

        {message.citations && message.citations.length > 0 && (
          <div className="mt-2">
            <button
              onClick={() => setShowCites((v) => !v)}
              className="text-[11px] font-medium"
              style={{ color: "var(--accent-bright)" }}
            >
              {showCites ? "Hide" : "Show"} {message.citations.length} cited section
              {message.citations.length === 1 ? "" : "s"}
            </button>
            {showCites && (
              <div className="mt-1.5 space-y-1.5">
                {message.citations.map((c) => (
                  <div
                    key={c.citation}
                    className="text-[11px] rounded-md px-2 py-1.5"
                    style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
                  >
                    <div className="font-semibold" style={{ color: "var(--text-primary)" }}>
                      {c.citation} — {c.title}
                    </div>
                    <div className="mt-0.5 leading-snug" style={{ color: "var(--text-secondary)" }}>
                      {c.text.length > 220 ? `${c.text.slice(0, 220)}…` : c.text}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
