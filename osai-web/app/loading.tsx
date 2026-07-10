export default function Loading() {
  return (
    <main
      aria-busy="true"
      aria-label="Loading workspace"
      style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "var(--text-secondary)" }}
    >
      Loading workspace...
    </main>
  );
}
