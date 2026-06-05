"use client";

// Modal: mint a share link for a report.
//
// Why this is its own component: the same dialog is opened from the
// dashboard ("Share this report") AND from the report detail page, and we
// want the share-token list to refetch identically in both places.
import { useEffect, useState } from "react";
import { Copy, Link as LinkIcon, Mail, Trash2, X } from "lucide-react";
import { createShare, listShares, revokeShare, type Share } from "@/lib/api";

type Role = "viewer" | "commenter";

export function ShareDialog({
  jobId,
  onClose,
}: {
  jobId: string;
  onClose: () => void;
}) {
  const [shares, setShares] = useState<Share[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("commenter");
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, [jobId]);

  async function refresh() {
    try {
      setLoading(true);
      const { shares } = await listShares(jobId);
      // Cast to Share shape (backend includes the public URL too in created
      // shares; list endpoint omits it, so we synthesize)
      const origin = typeof window !== "undefined" ? window.location.origin : "";
      setShares(
        shares.map((s: Share) => ({
          ...s,
          share_url: s.share_url || `${origin}/shared/${s.token}`,
        })),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load shares");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setCreating(true);
    try {
      await createShare(jobId, {
        invited_email: email || undefined,
        invited_name: name || undefined,
        role,
        expires_in_days: 30,
      });
      setEmail("");
      setName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create share");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(shareId: string) {
    if (!confirm("Revoke this share link? Anyone who has it will lose access.")) return;
    try {
      await revokeShare(jobId, shareId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to revoke");
    }
  }

  function copy(text: string, id: string) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 1500);
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-5 border-b"
             style={{ borderColor: "var(--border)" }}>
          <div>
            <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
              Share this report
            </h2>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Invite contractors or building inspectors. They don't need a Up2Code account.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" style={{ color: "var(--text-muted)" }}>
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleCreate} className="p-5 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Their name <span style={{ color: "var(--text-muted)" }}>(optional)</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="John from Acme Contracting"
                className="w-full px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Their email <span style={{ color: "var(--text-muted)" }}>(optional)</span>
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="them@firm.com"
                className="w-full px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
              They can…
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setRole("commenter")}
                className="flex-1 px-3 py-2 rounded-lg text-sm font-medium"
                style={{
                  background: role === "commenter" ? "var(--text-primary)" : "var(--bg-elevated)",
                  color: role === "commenter" ? "#fff" : "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              >
                View & comment
              </button>
              <button
                type="button"
                onClick={() => setRole("viewer")}
                className="flex-1 px-3 py-2 rounded-lg text-sm font-medium"
                style={{
                  background: role === "viewer" ? "var(--text-primary)" : "var(--bg-elevated)",
                  color: role === "viewer" ? "#fff" : "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              >
                View only
              </button>
            </div>
          </div>

          {error && (
            <p className="text-xs px-3 py-2 rounded-lg"
               style={{ background: "var(--non-compliant-bg)", color: "var(--non-compliant)" }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={creating}
            className="w-full font-medium py-2.5 rounded-lg disabled:opacity-60"
            style={{ background: "var(--btn-primary-bg)", color: "#fff" }}
          >
            {creating ? "Generating link…" : "Generate share link"}
          </button>
        </form>

        <div className="border-t" style={{ borderColor: "var(--border)" }}>
          <div className="p-5">
            <p className="text-xs font-medium uppercase tracking-wide mb-3"
               style={{ color: "var(--text-muted)" }}>
              Existing shares
            </p>
            {loading ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</p>
            ) : shares.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                No shares yet. Generate one above.
              </p>
            ) : (
              <ul className="space-y-2 max-h-60 overflow-y-auto">
                {shares.map((s) => {
                  const isRevoked = !!s.revoked_at;
                  return (
                    <li
                      key={s.id}
                      className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm"
                      style={{
                        background: "var(--bg-elevated)",
                        opacity: isRevoked ? 0.5 : 1,
                      }}
                    >
                      <LinkIcon className="w-4 h-4 flex-none" style={{ color: "var(--text-muted)" }} />
                      <div className="flex-1 min-w-0">
                        <div className="truncate font-medium" style={{ color: "var(--text-primary)" }}>
                          {s.invited_name || s.invited_email || "Open link"}
                        </div>
                        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                          {s.role} · {s.last_used_at ? `last opened ${new Date(s.last_used_at).toLocaleDateString()}` : "never opened"}
                          {isRevoked && " · revoked"}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => copy(s.share_url, s.id)}
                        title="Copy link"
                        className="p-1.5 rounded"
                        style={{ color: "var(--text-muted)" }}
                      >
                        <Copy className="w-4 h-4" />
                        {copiedId === s.id && (
                          <span className="ml-1 text-xs" style={{ color: "var(--accent)" }}>copied!</span>
                        )}
                      </button>
                      {s.invited_email && (
                        <a
                          href={`mailto:${s.invited_email}?subject=${encodeURIComponent("Up2Code AI compliance review")}&body=${encodeURIComponent(`I'm sharing a compliance review with you on Up2Code AI:\n\n${s.share_url}\n\nThis link gives you ${s.role} access — no signup required.`)}`}
                          className="p-1.5 rounded"
                          style={{ color: "var(--text-muted)" }}
                          title="Email this link"
                        >
                          <Mail className="w-4 h-4" />
                        </a>
                      )}
                      {!isRevoked && (
                        <button
                          type="button"
                          onClick={() => handleRevoke(s.id)}
                          className="p-1.5 rounded"
                          style={{ color: "var(--non-compliant)" }}
                          title="Revoke"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
