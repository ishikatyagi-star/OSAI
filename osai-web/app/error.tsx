"use client";

// Route-level error boundary: contains any render/runtime crash to the page
// body instead of blanking the whole app, reports it, and offers a retry.

import { useEffect } from "react";
import { reportClientError } from "@/lib/telemetry";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportClientError(error, "boundary");
  }, [error]);

  return (
    <div className="card" style={{ textAlign: "center", padding: "44px 24px", margin: "48px auto", maxWidth: 480 }}>
      <p className="text-body font-semibold" style={{ marginBottom: 6 }}>
        Something went wrong on this page
      </p>
      <p className="meta" style={{ maxWidth: 400, margin: "0 auto 16px" }}>
        The rest of Sheldon is fine. Our team has been notified. Try again, or
        head back to the dashboard.
      </p>
      <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
        <button type="button" className="btn btn-primary" onClick={() => reset()}>
          Try again
        </button>
        <a className="btn" href="/dashboard">
          Go to dashboard
        </a>
      </div>
    </div>
  );
}
