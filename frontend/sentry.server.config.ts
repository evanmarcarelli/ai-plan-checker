// Sentry server-side init for Next.js Node runtime.
// DSN comes from NEXT_PUBLIC_SENTRY_DSN — when unset, this is a no-op.
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: 0.1,
    environment: process.env.NEXT_PUBLIC_VERCEL_ENV || "development",
  });
}
