"use client";

// Inline comment thread for a single finding.
//
// Works in two modes:
//   - Owner mode  : no shareToken passed; uses the Supabase JWT
//   - Guest mode  : shareToken + guestName passed; backend authorizes via token
//
// Comments are flat (no nesting) — a code-review discussion is short and
// chronological, threads would be overkill.
import { useEffect, useState } from "react";
import { MessageSquare, Send } from "lucide-react";
import { addFindingComment, listFindingComments, type FindingComment } from "@/lib/api";

export function FindingComments({
  findingRef,
  jobId,
  shareToken,
  guestName,
  canComment,
  initialCount,
}: {
  findingRef: string;
  jobId: string;
  shareToken?: string;
  guestName?: string;
  canComment: boolean;
  initialCount?: number;
}) {
  const [open, setOpen] = useState(false);
  const [comments, setComments] = useState<FindingComment[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const { comments } = await listFindingComments(jobId, findingRef, { shareToken, guestName });
      setComments(comments);
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load comments");
    }
  }

  useEffect(() => {
    if (open && !loaded) void load();
  }, [open]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    setPosting(true);
    setError(null);
    try {
      await addFindingComment(jobId, findingRef, draft.trim(), {
        shareToken,
        guestName,
        authorDisplay: guestName,
      });
      setDraft("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to post comment");
    } finally {
      setPosting(false);
    }
  }

  return (
    <div className="mt-3 pt-3 border-t" style={{ borderColor: "var(--border)" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs font-medium"
        style={{ color: "var(--text-muted)" }}
      >
        <MessageSquare className="w-3.5 h-3.5" />
        {(() => {
          const count = loaded ? comments.length : (initialCount ?? 0);
          return count > 0
            ? `${count} comment${count === 1 ? "" : "s"}`
            : "Discuss this finding";
        })()}
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          {loaded && comments.length === 0 && (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              No comments yet. Start the discussion.
            </p>
          )}

          {comments.map((c) => (
            <div key={c.id} className="text-sm">
              <div className="flex items-baseline gap-2">
                <span className="font-medium" style={{ color: "var(--text-primary)" }}>
                  {c.author_display}
                </span>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {new Date(c.created_at).toLocaleString()}
                </span>
              </div>
              <p className="leading-relaxed mt-0.5" style={{ color: "var(--text-secondary)" }}>
                {c.body}
              </p>
            </div>
          ))}

          {canComment ? (
            <form onSubmit={submit} className="flex items-start gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Add a comment for your team…"
                rows={2}
                className="flex-1 px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
              <button
                type="submit"
                disabled={posting || !draft.trim()}
                className="p-2 rounded-lg disabled:opacity-50"
                style={{ background: "var(--btn-primary-bg)", color: "#fff" }}
                aria-label="Post comment"
              >
                <Send className="w-4 h-4" />
              </button>
            </form>
          ) : (
            <p className="text-xs italic" style={{ color: "var(--text-muted)" }}>
              {shareToken
                ? "This share is view-only — you can read the discussion but not post."
                : "Enter your name above to join the discussion."}
            </p>
          )}

          {error && (
            <p className="text-xs" style={{ color: "var(--non-compliant)" }}>{error}</p>
          )}
        </div>
      )}
    </div>
  );
}
