"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft } from "lucide-react";

export default function PrivacyPage() {
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
            Privacy Policy
          </h1>
          <p className="text-xs mb-8" style={{ color: "var(--text-muted)" }}>
            Last updated May 13, 2026
          </p>

          <p className="mb-4">
            This Privacy Notice for Up 2 Code Inc. (doing business as PhiCodes) (&quot;we,&quot;
            &quot;us,&quot; or &quot;our&quot;), describes how and why we might access, collect,
            store, use, and/or share (&quot;process&quot;) your personal information when you use
            our services (&quot;Services&quot;), including when you:
          </p>
          <ul className="list-disc pl-6 mb-4 space-y-1">
            <li>
              Visit our website at{" "}
              <a href="http://www.up2code.ai" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
                http://www.up2code.ai
              </a>{" "}
              or any website of ours that links to this Privacy Notice
            </li>
            <li>Engage with us in other related ways, including any marketing or events</li>
          </ul>
          <p className="mb-8">
            Questions or concerns? Reading this Privacy Notice will help you understand your privacy
            rights and choices. We are responsible for making decisions about how your personal
            information is processed. If you do not agree with our policies and practices, please do
            not use our Services. If you still have any questions or concerns, please contact us at{" "}
            <a href="mailto:esmith.marc@gmail.com" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              esmith.marc@gmail.com
            </a>
            .
          </p>

          <H2>Summary of key points</H2>
          <p className="mb-3">
            This summary provides key points from our Privacy Notice, but you can find out more details
            about any of these topics by clicking the link following each key point or by using our table
            of contents below to find the section you are looking for.
          </p>
          <p className="mb-3">
            <Em>What personal information do we process?</Em> When you visit, use, or navigate our
            Services, we may process personal information depending on how you interact with us and the
            Services, the choices you make, and the products and features you use.
          </p>
          <p className="mb-3">
            <Em>Do we process any sensitive personal information?</Em> Some of the information may be
            considered &quot;special&quot; or &quot;sensitive&quot; in certain jurisdictions, for example
            your racial or ethnic origins, sexual orientation, and religious beliefs. We may process
            sensitive personal information when necessary with your consent or as otherwise permitted by
            applicable law.
          </p>
          <p className="mb-3">
            <Em>Do we collect any information from third parties?</Em> We do not collect any information
            from third parties.
          </p>
          <p className="mb-3">
            <Em>How do we process your information?</Em> We process your information to provide, improve,
            and administer our Services, communicate with you, for security and fraud prevention, and to
            comply with law. We may also process your information for other purposes with your consent. We
            process your information only when we have a valid legal reason to do so.
          </p>
          <p className="mb-3">
            <Em>In what situations and with which parties do we share personal information?</Em> We may
            share information in specific situations and with specific third parties.
          </p>
          <p className="mb-3">
            <Em>How do we keep your information safe?</Em> We have adequate organizational and technical
            processes and procedures in place to protect your personal information. However, no electronic
            transmission over the internet or information storage technology can be guaranteed to be 100%
            secure, so we cannot promise or guarantee that hackers, cybercriminals, or other unauthorized
            third parties will not be able to defeat our security and improperly collect, access, steal, or
            modify your information.
          </p>
          <p className="mb-3">
            <Em>What are your rights?</Em> Depending on where you are located geographically, the
            applicable privacy law may mean you have certain rights regarding your personal information.
          </p>
          <p className="mb-8">
            <Em>How do you exercise your rights?</Em> The easiest way to exercise your rights is by
            submitting a data subject access request, or by contacting us. We will consider and act upon
            any request in accordance with applicable data protection laws.
          </p>

          <H2>1. What information do we collect?</H2>
          <H3>Personal information you disclose to us</H3>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: We collect personal information that you provide to us.
          </p>
          <p className="mb-3">
            We collect personal information that you voluntarily provide to us when you register on the
            Services, express an interest in obtaining information about us or our products and Services,
            when you participate in activities on the Services, or otherwise when you contact us.
          </p>
          <p className="mb-3">
            <strong style={{ color: "var(--text-primary)" }}>Personal Information Provided by You.</strong>{" "}
            The personal information that we collect depends on the context of your interactions with us
            and the Services, the choices you make, and the products and features you use. The personal
            information we collect may include the following:
          </p>
          <ul className="list-disc pl-6 mb-4 space-y-1">
            <li>email addresses</li>
            <li>usernames</li>
            <li>passwords</li>
            <li>billing addresses</li>
            <li>names</li>
          </ul>
          <p className="mb-3">
            <strong style={{ color: "var(--text-primary)" }}>Sensitive Information.</strong> When necessary,
            with your consent or as otherwise permitted by applicable law, we process the following
            categories of sensitive information:
          </p>
          <ul className="list-disc pl-6 mb-4 space-y-1">
            <li>financial data</li>
          </ul>
          <p className="mb-3">
            <strong style={{ color: "var(--text-primary)" }}>Payment Data.</strong> We may collect data
            necessary to process your payment if you choose to make purchases, such as your payment
            instrument number, and the security code associated with your payment instrument. All payment
            data is handled and stored by Stripe. You may find their privacy notice link here:{" "}
            <a href="https://stripe.com/privacy" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              https://stripe.com/privacy
            </a>
            .
          </p>
          <p className="mb-8">
            All personal information that you provide to us must be true, complete, and accurate, and you
            must notify us of any changes to such personal information.
          </p>

          <H2>2. How do we process your information?</H2>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: We process your information to provide, improve, and administer our Services,
            communicate with you, for security and fraud prevention, and to comply with law.
          </p>
          <ul className="list-disc pl-6 mb-8 space-y-2">
            <li>To facilitate account creation and authentication and otherwise manage user accounts.</li>
            <li>To fulfill and manage your orders, payments, returns, and exchanges.</li>
            <li>To protect our Services, including fraud monitoring and prevention.</li>
            <li>To evaluate and improve our Services, products, marketing, and your experience.</li>
            <li>To identify usage trends so we can improve the Services.</li>
          </ul>

          <H2>3. When and with whom do we share your personal information?</H2>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: We may share information in specific situations described in this section and/or with
            the following third parties.
          </p>
          <ul className="list-disc pl-6 mb-8 space-y-2">
            <li>
              <strong style={{ color: "var(--text-primary)" }}>Business Transfers.</strong> In connection
              with any merger, sale of assets, financing, or acquisition.
            </li>
            <li>
              <strong style={{ color: "var(--text-primary)" }}>Affiliates.</strong> With our affiliates,
              required to honor this Privacy Notice.
            </li>
            <li>
              <strong style={{ color: "var(--text-primary)" }}>Business Partners.</strong> To offer
              products, services, or promotions.
            </li>
          </ul>

          <H2>4. Do we use cookies and other tracking technologies?</H2>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: We may use cookies and other tracking technologies to collect and store your
            information.
          </p>
          <p className="mb-3">
            We may use cookies and similar tracking technologies (like web beacons and pixels) to gather
            information when you interact with our Services. Some online tracking technologies help us
            maintain the security of our Services and your account, prevent crashes, fix bugs, save your
            preferences, and assist with basic site functions.
          </p>
          <p className="mb-3">
            We also permit third parties and service providers to use online tracking technologies on our
            Services for analytics and advertising.
          </p>
          <H3>Google Analytics</H3>
          <p className="mb-8">
            We may share your information with Google Analytics to track and analyze the use of the
            Services. To opt out, visit{" "}
            <a href="https://tools.google.com/dlpage/gaoptout" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              https://tools.google.com/dlpage/gaoptout
            </a>
            .
          </p>

          <H2>5. Do we offer artificial intelligence-based products?</H2>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: We offer products, features, or tools powered by artificial intelligence, machine
            learning, or similar technologies.
          </p>
          <p className="mb-3">
            We provide the AI Products through third-party service providers (&quot;AI Service Providers&quot;),
            including Anthropic. Your input, output, and personal information will be shared with and processed
            by these AI Service Providers to enable your use of our AI Products. You must not use the AI
            Products in any way that violates the terms or policies of any AI Service Provider.
          </p>
          <p className="mb-8">
            Our AI Products are designed for: AI applications, AI research, and AI search. All personal
            information processed using our AI Products is handled in line with this Privacy Notice and our
            agreement with third parties.
          </p>

          <H2>6. How long do we keep your information?</H2>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: We keep your information for as long as necessary to fulfill the purposes outlined in
            this Privacy Notice unless otherwise required by law.
          </p>
          <p className="mb-8">
            We will only keep your personal information for as long as it is necessary for the purposes set
            out in this Privacy Notice, unless a longer retention period is required or permitted by law.
            No purpose in this notice will require us keeping your personal information for longer than the
            period of time in which users have an account with us.
          </p>

          <H2>7. How do we keep your information safe?</H2>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: We aim to protect your personal information through a system of organizational and
            technical security measures.
          </p>
          <p className="mb-8">
            We have implemented appropriate and reasonable technical and organizational security measures
            designed to protect the security of any personal information we process. However, despite our
            safeguards and efforts to secure your information, no electronic transmission over the Internet
            or information storage technology can be guaranteed to be 100% secure.
          </p>

          <H2>8. Do we collect information from minors?</H2>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: We do not knowingly collect data from or market to children under 18 years of age.
          </p>
          <p className="mb-8">
            By using the Services, you represent that you are at least 18 or the parent or guardian of such
            a minor. If you become aware of any data we may have collected from children under age 18,
            please contact us at{" "}
            <a href="mailto:esmith.marc@gmail.com" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              esmith.marc@gmail.com
            </a>
            .
          </p>

          <H2>9. What are your privacy rights?</H2>
          <p className="italic mb-3" style={{ color: "var(--text-muted)" }}>
            In Short: You may review, change, or terminate your account at any time.
          </p>
          <p className="mb-3">
            <strong style={{ color: "var(--text-primary)" }}>Withdrawing your consent:</strong> If we are
            relying on your consent to process your personal information, you have the right to withdraw
            your consent at any time by contacting us.
          </p>
          <p className="mb-3">
            <strong style={{ color: "var(--text-primary)" }}>Account Information:</strong> If you would
            like to review, change, or terminate your account, you can do so from the{" "}
            <Link href="/account" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              Account page
            </Link>{" "}
            or by contacting us.
          </p>
          <p className="mb-8">
            <strong style={{ color: "var(--text-primary)" }}>Cookies and similar technologies:</strong> Most
            Web browsers are set to accept cookies by default. If you prefer, you can choose to set your
            browser to remove or reject cookies, which may affect certain features of the Services.
          </p>

          <H2>10. Controls for Do-Not-Track features</H2>
          <p className="mb-8">
            Most web browsers include a Do-Not-Track (&quot;DNT&quot;) feature. At this stage, no uniform
            technology standard for recognizing DNT signals has been finalized. As such, we do not currently
            respond to DNT browser signals. If a standard is adopted that we must follow in the future, we
            will inform you in a revised version of this Privacy Notice.
          </p>

          <H2>11. Do we make updates to this notice?</H2>
          <p className="mb-8">
            We may update this Privacy Notice from time to time. The updated version will be indicated by
            an updated &quot;Revised&quot; date at the top. If we make material changes, we may notify you
            by prominently posting a notice of such changes or by directly sending you a notification.
          </p>

          <H2>12. How can you contact us about this notice?</H2>
          <p className="mb-3">
            If you have questions or comments about this notice, you may email us at{" "}
            <a href="mailto:esmith.marc@gmail.com" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              esmith.marc@gmail.com
            </a>{" "}
            or contact us by post at:
          </p>
          <address className="not-italic mb-8" style={{ color: "var(--text-primary)" }}>
            Up 2 Code Inc.<br />
            4751 21st Ave NE, 105<br />
            Seattle, WA 98105<br />
            United States
          </address>

          <H2>13. How can you review, update, or delete the data we collect from you?</H2>
          <p className="mb-3">
            Based on the applicable laws of your country, you may have the right to request access to the
            personal information we collect from you, details about how we have processed it, correct
            inaccuracies, or delete your personal information. To do so, visit the{" "}
            <Link href="/account" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              Account page
            </Link>{" "}
            or contact us at{" "}
            <a href="mailto:esmith.marc@gmail.com" className="hover:underline" style={{ color: "var(--accent-bright)" }}>
              esmith.marc@gmail.com
            </a>
            .
          </p>
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

function H3({ children }: { children: React.ReactNode }) {
  return (
    <h3
      className="text-base font-semibold mt-5 mb-2"
      style={{ color: "var(--text-primary)" }}
    >
      {children}
    </h3>
  );
}

function Em({ children }: { children: React.ReactNode }) {
  return <strong style={{ color: "var(--text-primary)" }}>{children}</strong>;
}
