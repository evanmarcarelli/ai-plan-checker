// Sentry Node-runtime init for Next.js Server Components, Route Handlers,
// Server Actions, and Middleware running in the Node runtime.
//
// Loaded by `instrumentation.ts` when NEXT_RUNTIME === "nodejs".
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN || process.env.NEXT_PUBLIC_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.VERCEL_ENV || process.env.NODE_ENV || "development",
    release: process.env.VERCEL_GIT_COMMIT_SHA || undefined,

    tracesSampleRate: process.env.NODE_ENV === "development" ? 1.0 : 0.1,

    // Attach local variable values to stack frames so a TypeError on the
    // server tells us WHICH variable was undefined. Server-side only.
    includeLocalVariables: true,

    sendDefaultPii: false,

    enableLogs: true,
  });
}
