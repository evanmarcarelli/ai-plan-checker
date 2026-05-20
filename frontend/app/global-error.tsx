"use client";

// Catches errors that escape the rest of the React tree — including failures
// inside the root layout. Without this file, those errors render as a blank
// white page in production and Sentry never sees them.
//
// Per the Sentry Next.js SDK skill: this file MUST have "use client" as its
// very first line, otherwise the captureException call is a no-op.
import * as Sentry from "@sentry/nextjs";
import NextError from "next/error";
import { useEffect } from "react";

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html>
      <body>
        <NextError statusCode={0} />
      </body>
    </html>
  );
}
