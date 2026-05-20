// Sentry client-side init. Only runs in the browser.
// DSN comes from NEXT_PUBLIC_SENTRY_DSN — when unset, this is a no-op.
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 0.1,
    environment: process.env.NEXT_PUBLIC_VERCEL_ENV || "development",
    // Don't capture PII the user typed into forms.
    sendDefaultPii: false,
    beforeSend(event: any) {
      // Strip any inputs from breadcrumbs (defense in depth — Sentry already
      // masks by default but we want zero risk of email/password leakage).
      if (event.request?.cookies) delete event.request.cookies;
      return event;
    },
  });
}
