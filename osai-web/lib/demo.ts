// Demo-mode gate. By default Sheldon shows real synced data (or empty states); the
// bundled DEMO_* fixtures are only used when demo mode is explicitly on. This
// keeps a customer's workspace free of sample content once they connect tools.
//
// Demo mode is active when ANY of:
//   - NEXT_PUBLIC_OSAI_DEMO=1 at build time (e.g. the pitch deployment), or
//   - localStorage `osai_demo` === "1", or
//   - the session org is the shared "demo-org" (the /demo + "Try Demo" path).
export function isDemo(): boolean {
  if (process.env.NEXT_PUBLIC_OSAI_DEMO === "1") return true;
  if (typeof window === "undefined") return false;
  return (
    localStorage.getItem("osai_demo") === "1" ||
    localStorage.getItem("osai_org_id") === "demo-org"
  );
}

// Pick `demo` when demo mode is on, otherwise the real value. Helper to keep the
// page-level pattern terse: `useState(demoOr(DEMO_X, []))`.
export function demoOr<T>(demo: T, real: T): T {
  return isDemo() ? demo : real;
}
