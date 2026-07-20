// Frontend crash reporting. Error boundaries call this so a blank screen is
// never invisible to the team: the backend logs it and forwards to Sentry when
// configured. Fire-and-forget by design: telemetry must never cause a second
// failure or block the retry UI.

export function reportClientError(error: unknown, source: "boundary" | "global"): void {
  try {
    const err = error instanceof Error ? error : new Error(String(error));
    void fetch("/api/internal/client-errors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: err.message.slice(0, 4000),
        stack: (err.stack ?? "").slice(0, 4000),
        path: typeof window === "undefined" ? "" : window.location.pathname,
        source,
      }),
      keepalive: true,
    }).catch(() => {});
  } catch {
    // Never throw from telemetry.
  }
}
