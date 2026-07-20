"use client";

// Last-resort boundary: catches crashes in the root layout itself. Replaces the
// entire document, so it cannot rely on app CSS; styles are inline.

import { useEffect } from "react";
import { reportClientError } from "@/lib/telemetry";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportClientError(error, "global");
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          background: "#f7f6f3",
          color: "#1a1a1a",
        }}
      >
        <div style={{ textAlign: "center", maxWidth: 420, padding: 24 }}>
          <p style={{ fontSize: 17, fontWeight: 600, marginBottom: 8 }}>
            Sheldon hit an unexpected error
          </p>
          <p style={{ fontSize: 14, color: "#666", marginBottom: 20 }}>
            Our team has been notified. Reloading usually fixes this.
          </p>
          <button
            type="button"
            onClick={() => reset()}
            style={{
              padding: "10px 18px",
              borderRadius: 10,
              border: "none",
              background: "#1a1a1a",
              color: "#fff",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Reload
          </button>
        </div>
      </body>
    </html>
  );
}
