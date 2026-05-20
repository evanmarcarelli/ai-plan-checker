// Sentry browser/client runtime init.
//
// Per the Sentry Next.js SDK skill (Nov 2025 pattern), the file MUST be named
// `instrumentation-client.ts` at the project root — not the older
// `sentry.client.config.ts`. Next.js loads it automatically for the client
// bundle, and `onRouterTransitionStart` below wires App Router navigation
// spans into the trace.
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_VERCEL_ENV || process.env.NODE_ENV || "development",
    release: process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA || undefined,

    // 100% in dev so we see everything; 10% in prod to stay inside the free quota
    tracesSampleRate: process.env.NODE_ENV === "development" ? 1.0 : 0.1,

    // Session Replay: 10% of all sessions, 100% of sessions with errors.
    // Replay only kicks in when replayIntegration is added to integrations below.
    replaysSessionSampleRate: 0.1,
    replaysOnErrorSampleRate: 1.0,

    // We sign up architects/inspectors — keep IP, headers, and user data
    // OUT of error events until we have a documented privacy policy update.
    // Re-evaluate after legal review.
    sendDefaultPii: false,

    enableLogs: true,

    integrations: [
      Sentry.replayIntegration({
        // Default-mask any text/input that could contain PII (names, emails,
        // plan addresses, comments). Architects routinely paste sensitive
        // project metadata into forms.
        maskAllText: true,
        maskAllInputs: true,
        blockAllMedia: true,
      }),
    ],

    beforeSend(event: any) {
      // Defense in depth: never let cookies leave the browser via Sentry.
      if (event.request?.cookies) delete event.request.cookies;
      return event;
    },
  });
}

// App Router navigation tracing hook. Required so Sentry sees client-side
// route transitions as spans inside a request trace.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
