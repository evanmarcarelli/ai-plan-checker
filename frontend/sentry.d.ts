// Type shim so `tsc --noEmit` works locally without `npm install @sentry/nextjs`
// having been run. Vercel installs the real package at build time, which
// provides the real types and supersedes this declaration.
declare module "@sentry/nextjs";
