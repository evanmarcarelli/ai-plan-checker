"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft } from "lucide-react";

export default function RefundPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen px-6 py-12" style={{ background: "var(--bg)" }}>
      <div className="max-w-3xl mx-auto">
        <button
          onClick={() => router.back()}
          className="inline-flex items-center gap-1.5 text-sm mb-8 hover:underline"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronLeft className="w-4 h-4" />
          Back
        </button>

        <article
          className="rounded-xl p-8 leading-relaxed"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            color: "var(--text-secondary)",
          }}
        >
          <h1
            className="text-3xl font-bold mb-2"
            style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
          >
            Refund Policy
          </h1>
          <p className="text-xs mb-8" style={{ color: "var(--text-muted)" }}>
            Last updated May 13, 2026
          </p>

          <H2>Summary</H2>
          <p className="mb-4">
            <strong style={{ color: "var(--text-primary)" }}>All purchases are non-refundable.</strong>{" "}
            We offer one free pre-submittal review on signup so you can evaluate the Services before
            you pay. Subscriptions can be canceled at any time from your account page — you keep
            access through the end of the billing period you&apos;ve already paid for, and you are
            not charged again.
          </p>

          <H2>Free trial</H2>
          <p className="mb-4">
            Every new account receives <strong style={{ color: "var(--text-primary)" }}>one (1) free review</strong>{" "}
            on signup. This is your opportunity to evaluate the accuracy and usefulness of our AI Plan
            Checker before subscribing. We strongly recommend using this free credit before purchasing
            a paid plan.
          </p>

          <H2>Paid subscriptions</H2>
          <p className="mb-3">All paid subscriptions are billed in advance on a monthly basis. By subscribing you agree:</p>
          <ul className="list-disc pl-6 mb-4 space-y-2">
            <li>You authorize us to charge your payment method on a recurring monthly basis until you cancel.</li>
            <li>All charges are non-refundable, including but not limited to partial months of service, unused reviews, and downgrades.</li>
            <li>If you cancel mid-cycle, you retain access to your paid plan until the end of the current billing period. You will not be charged again.</li>
            <li>You can manage or cancel your subscription at any time from your{" "}
              <Link href="/account" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
                Account page
              </Link>
              {" "}or via the Stripe Customer Portal.
            </li>
          </ul>

          <H2>Limited exceptions</H2>
          <p className="mb-3">
            We may, at our sole discretion, issue a refund in the following limited circumstances:
          </p>
          <ul className="list-disc pl-6 mb-4 space-y-2">
            <li>
              <strong style={{ color: "var(--text-primary)" }}>Duplicate charge:</strong> If our
              billing system charges you twice for the same period due to a technical error, we will
              refund the duplicate charge in full.
            </li>
            <li>
              <strong style={{ color: "var(--text-primary)" }}>Service outage:</strong> If the
              Services are unavailable for an extended period due to our fault (not a planned
              maintenance window) and we cannot deliver the credits you paid for that billing cycle,
              we will credit your account or refund a prorated amount.
            </li>
            <li>
              <strong style={{ color: "var(--text-primary)" }}>Unauthorized charge:</strong> If your
              payment method was used without your authorization, contact us within{" "}
              <strong style={{ color: "var(--text-primary)" }}>30 days</strong> of the charge and we
              will work with you and Stripe to resolve the dispute.
            </li>
          </ul>

          <H2>How to request a refund</H2>
          <p className="mb-3">
            If you believe you qualify for a refund under the limited exceptions above, email us at{" "}
            <a href="mailto:esmith.marc@gmail.com" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              esmith.marc@gmail.com
            </a>{" "}
            with:
          </p>
          <ul className="list-disc pl-6 mb-4 space-y-1">
            <li>The email address associated with your account</li>
            <li>The approximate date and amount of the charge</li>
            <li>A brief description of why you believe a refund is warranted</li>
          </ul>
          <p className="mb-4">
            We will respond within five (5) business days. Approved refunds are issued to the
            original payment method via Stripe and typically appear within 5–10 business days
            depending on your card issuer.
          </p>

          <H2>Chargebacks</H2>
          <p className="mb-4">
            We ask that you contact us at{" "}
            <a href="mailto:esmith.marc@gmail.com" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              esmith.marc@gmail.com
            </a>{" "}
            before initiating a chargeback with your bank. Most billing issues can be resolved
            quickly by email. Chargebacks initiated without first contacting us may result in your
            account being suspended.
          </p>

          <H2>Why we don&apos;t offer general refunds</H2>
          <p className="mb-4">
            Each plan review consumes significant compute resources at our AI provider (typically
            $0.50–$2 per review). Once a review has been run, that cost cannot be recovered. The
            free first review is designed to let you evaluate the product without financial risk.
          </p>

          <H2>Questions</H2>
          <p className="mb-4">
            For any question about billing or this policy, contact:
          </p>
          <address className="not-italic mb-4" style={{ color: "var(--text-primary)" }}>
            <strong>Up 2 Code Inc.</strong>
            <br />
            4751 21st Ave NE, 105
            <br />
            Seattle, WA 98105
            <br />
            <a
              href="mailto:esmith.marc@gmail.com"
              className="hover:underline"
              style={{ color: "var(--accent-bright)" }}
            >
              esmith.marc@gmail.com
            </a>
          </address>
        </article>
      </div>
    </div>
  );
}

function H2({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="text-xl font-bold mt-8 mb-3"
      style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
    >
      {children}
    </h2>
  );
}
