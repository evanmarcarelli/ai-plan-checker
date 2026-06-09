"use client";

// Public feedback board. Anyone signed in can post requests/issues and
// upvote what others have posted. Sorted by vote count.
//
// Behavior choices:
//  - Vote button is a toggle; clicking again removes your vote.
//  - Author's display name comes from their profile, with an optional
//    per-post override field in case they want to post under their firm name.
//  - Status badges (open, considering, planned, shipped, wontfix) are set by
//    the founder via Supabase or a future admin UI. Today posts default open.
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowBigUp, MessageSquarePlus, Building2 } from "lucide-react";
import { listFeedback, createFeedback, toggleFeedbackVote, type FeedbackPost } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";


export default function FeedbackPage() {
  const router = useRouter();
  const [posts, setPosts] = useState<FeedbackPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    // Require auth — bounce to login if not signed in
    const sb = createClient();
    sb.auth.getSession().then(({ data: { session } }) => {
      if (!session) {
        router.push("/login?redirect=/feedback");
        return;
      }
      void refresh();
    });
  }, [router]);

  async function refresh() {
    try {
      setLoading(true);
      setError(null);
      const { posts } = await listFeedback();
      setPosts(posts);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function handleVote(postId: string) {
    // Optimistic update
    setPosts((cur) =>
      cur.map((p) =>
        p.id === postId
          ? { ...p, user_has_voted: !p.user_has_voted, votes: p.votes + (p.user_has_voted ? -1 : 1) }
          : p
      )
    );
    try {
      await toggleFeedbackVote(postId);
    } catch (e) {
      void refresh(); // revert on failure
      setError(e instanceof Error ? e.message : "Vote failed");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <Header />
      <main className="max-w-3xl mx-auto px-6 py-10">
        <div className="flex items-start justify-between mb-6 gap-3">
          <div>
            <p className="text-xs uppercase tracking-widest mb-1" style={{ color: "var(--accent)" }}>
              Feedback
            </p>
            <h1
              className="text-3xl font-bold tracking-tight"
              style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
            >
              What should we build next?
            </h1>
            <p className="text-sm mt-2 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              Tell us what is missing or what would make PhiCodes AI easier to use. Upvote
              what you care about. The top items shape the roadmap.
            </p>
          </div>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex-shrink-0 inline-flex items-center gap-2 text-sm font-medium px-3 py-2 rounded-lg"
            style={{ background: "#0B0E14", color: "#fff" }}
          >
            <MessageSquarePlus className="w-4 h-4" />
            New post
          </button>
        </div>

        {showForm && <NewPostForm onCreated={() => { setShowForm(false); void refresh(); }} />}

        {error && (
          <p className="text-xs mb-4 px-3 py-2 rounded-lg"
             style={{ background: "var(--non-compliant-bg)", color: "var(--non-compliant)" }}>
            {error}
          </p>
        )}

        {loading ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</p>
        ) : posts.length === 0 ? (
          <div
            className="rounded-xl p-8 text-center text-sm"
            style={{ background: "var(--bg-card)", border: "1px dashed var(--border)", color: "var(--text-muted)" }}
          >
            No posts yet. Be the first to share an idea.
          </div>
        ) : (
          <ul className="space-y-2">
            {posts.map((p) => (
              <PostCard key={p.id} post={p} onVote={() => handleVote(p.id)} />
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}


function Header() {
  return (
    <header
      className="sticky top-0 z-30 px-6 py-3 border-b backdrop-blur"
      style={{ background: "rgba(255,255,255,0.85)", borderColor: "var(--border)" }}
    >
      <div className="max-w-3xl mx-auto flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <div
            className="inline-flex items-center justify-center w-8 h-8 rounded-lg"
            style={{ background: "#0B0E14" }}
          >
            <Building2 className="w-4 h-4 text-white" />
          </div>
          <span
            className="font-bold text-base tracking-tight"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            PhiCodes AI
          </span>
        </Link>
        <nav className="flex items-center gap-5 text-sm" style={{ color: "var(--text-secondary)" }}>
          <Link href="/" className="hover:underline">Home</Link>
          <Link href="/dashboard" className="hover:underline">Dashboard</Link>
          <span className="font-medium" style={{ color: "var(--text-primary)" }}>Feedback</span>
        </nav>
      </div>
    </header>
  );
}


function NewPostForm({ onCreated }: { onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [authorDisplay, setAuthorDisplay] = useState("");
  const [posting, setPosting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (title.trim().length < 3) {
      setErr("Title must be at least 3 characters.");
      return;
    }
    setPosting(true);
    setErr(null);
    try {
      await createFeedback({
        title: title.trim(),
        body: body.trim(),
        author_display: authorDisplay.trim() || undefined,
      });
      onCreated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to post");
    } finally {
      setPosting(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-xl p-4 mb-5 space-y-3"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        maxLength={200}
        placeholder="What is the request or issue?"
        className="w-full px-3 py-2 rounded-lg text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500"
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
      />
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        maxLength={4000}
        rows={4}
        placeholder="Details, context, screenshots in words. Optional."
        className="w-full px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
      />
      <div className="flex items-center gap-3">
        <input
          type="text"
          value={authorDisplay}
          onChange={(e) => setAuthorDisplay(e.target.value)}
          maxLength={80}
          placeholder="Post as (optional, e.g. Acme Architects)"
          className="flex-1 px-3 py-2 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
          style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
        />
        <button
          type="submit"
          disabled={posting || title.trim().length < 3}
          className="text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-50"
          style={{ background: "#0B0E14", color: "#fff" }}
        >
          {posting ? "Posting…" : "Post"}
        </button>
      </div>
      {err && (
        <p className="text-xs" style={{ color: "var(--non-compliant)" }}>{err}</p>
      )}
    </form>
  );
}


function PostCard({ post, onVote }: { post: FeedbackPost; onVote: () => void }) {
  return (
    <li
      className="flex gap-3 rounded-xl p-4"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <button
        onClick={onVote}
        className="flex-shrink-0 flex flex-col items-center justify-center w-12 rounded-lg py-2"
        style={{
          background: post.user_has_voted ? "var(--text-primary)" : "var(--bg-elevated)",
          color: post.user_has_voted ? "#fff" : "var(--text-primary)",
          border: "1px solid var(--border)",
        }}
        aria-label={post.user_has_voted ? "Remove vote" : "Upvote"}
      >
        <ArrowBigUp className="w-4 h-4" />
        <span className="text-sm font-bold leading-tight">{post.votes}</span>
      </button>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-baseline gap-2 mb-1">
          <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            {post.title}
          </h3>
          {post.status !== "open" && <StatusBadge status={post.status} />}
        </div>
        {post.body && (
          <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
            {post.body}
          </p>
        )}
        <div className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
          {post.author_display}
          {post.created_at && <> · {new Date(post.created_at).toLocaleDateString()}</>}
        </div>
      </div>
    </li>
  );
}


function StatusBadge({ status }: { status: string }) {
  const palette: Record<string, { bg: string; fg: string; label: string }> = {
    considering: { bg: "#FEF3C7", fg: "#92400E", label: "Considering" },
    planned:     { bg: "#DBEAFE", fg: "#1E40AF", label: "Planned" },
    shipped:     { bg: "#D1FAE5", fg: "#065F46", label: "Shipped" },
    wontfix:     { bg: "#F3F4F6", fg: "#6B7280", label: "Won't fix" },
  };
  const p = palette[status];
  if (!p) return null;
  return (
    <span
      className="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full"
      style={{ background: p.bg, color: p.fg }}
    >
      {p.label}
    </span>
  );
}
