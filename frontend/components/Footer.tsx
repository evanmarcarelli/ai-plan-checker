import Link from "next/link";

export default function Footer() {
  return (
    <footer
      className="px-6 py-6 border-t"
      style={{ borderColor: "var(--border)", background: "var(--bg)" }}
    >
      <div
        className="max-w-screen-2xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-xs"
        style={{ color: "var(--text-muted)" }}
      >
        <div>© {new Date().getFullYear()} Up 2 Code Inc. · AI Plan Checker</div>
        <nav className="flex items-center gap-5">
          <Link href="/privacy" className="hover:underline" style={{ color: "var(--text-secondary)" }}>
            Privacy
          </Link>
          <Link href="/terms" className="hover:underline" style={{ color: "var(--text-secondary)" }}>
            Terms
          </Link>
          <Link href="/refund" className="hover:underline" style={{ color: "var(--text-secondary)" }}>
            Refunds
          </Link>
          <a
            href="mailto:esmith.marc@gmail.com"
            className="hover:underline"
            style={{ color: "var(--text-secondary)" }}
          >
            Contact
          </a>
        </nav>
      </div>
    </footer>
  );
}
