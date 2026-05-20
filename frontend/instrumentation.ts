// Next.js calls register() once at server startup. We use it to dispatch the
// correct Sentry init file based on which runtime is booting (Node vs Edge).
// Pattern documented at:
//   https://docs.sentry.io/platforms/javascript/guides/nextjs/manual-setup/
import * as Sentry from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

// Auto-captures any unhandled server-side request error. Requires
// @sentry/nextjs >= 8.28.0 (we are on 10.53+ via package.json).
export const onRequestError = Sentry.captureRequestError;
