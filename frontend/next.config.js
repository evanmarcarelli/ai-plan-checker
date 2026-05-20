/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    serverComponentsExternalPackages: [],
  },
};

// Wrap with Sentry to enable source-map upload + ad-blocker bypass.
// withSentryConfig is a no-op when @sentry/nextjs isn't installed, so this is
// safe to leave in place even before SENTRY_AUTH_TOKEN is set on Vercel.
let exportedConfig = nextConfig;
try {
  const { withSentryConfig } = require("@sentry/nextjs");
  exportedConfig = withSentryConfig(nextConfig, {
    // From the wizard command you ran: org=up2code-rg, project=javascript-nextjs
    org: process.env.SENTRY_ORG || "up2code-rg",
    project: process.env.SENTRY_PROJECT || "javascript-nextjs",

    // Source-map upload auth token. Set SENTRY_AUTH_TOKEN as a Vercel build
    // env var (Project Settings → Environment Variables, NOT prefixed with
    // NEXT_PUBLIC_). Reads from .env.sentry-build-plugin locally.
    authToken: process.env.SENTRY_AUTH_TOKEN,

    // Upload a wider set of client files so stack traces resolve cleanly even
    // for code that's split across chunks.
    widenClientFileUpload: true,

    // Tunnel Sentry requests through this app's own /monitoring route so
    // ad-blockers and corporate firewalls don't drop telemetry.
    tunnelRoute: "/monitoring",

    // Quiet the build output unless we're in CI.
    silent: !process.env.CI,
  });
} catch (e) {
  // @sentry/nextjs not installed yet (fresh checkout) — skip Sentry config.
}

module.exports = exportedConfig;
