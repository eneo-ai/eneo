"use client";

import { useEffect } from "react";

/**
 * Last-resort boundary for errors thrown in the root layout/providers, where
 * the normal `(app)/error.tsx` can't render. It must supply its own
 * <html>/<body> because it replaces the root layout. Kept dependency-free
 * (no i18n/UI providers — they may be what failed) and English-only.
 */
export default function GlobalError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          display: "flex",
          minHeight: "100vh",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
          padding: "2rem"
        }}
      >
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Something went wrong</h1>
        {error.digest && (
          <p style={{ fontFamily: "monospace", fontSize: "0.75rem", opacity: 0.7 }}>
            Trace ID: {error.digest}
          </p>
        )}
        <button
          type="button"
          onClick={reset}
          style={{
            cursor: "pointer",
            borderRadius: "0.5rem",
            border: "1px solid currentColor",
            padding: "0.5rem 1rem"
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
