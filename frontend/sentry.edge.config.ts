// Sentry Edge-runtime init for Next.js middleware and Edge route handlers.
//
// Loaded by `instrumentation.ts` when NEXT_RUNTIME === "edge".
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN || process.env.NEXT_PUBLIC_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.VERCEL_ENV || process.env.NODE_ENV || "development",
    release: process.env.VERCEL_GIT_COMMIT_SHA || undefined,

    tracesSampleRate: process.env.NODE_ENV === "development" ? 1.0 : 0.1,

    sendDefaultPii: false,

    enableLogs: true,
  });
}
