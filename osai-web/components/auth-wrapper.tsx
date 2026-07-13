"use client";

import { useState, useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

// Pages that don't require authentication (handled by route handlers or their own UI)
const PUBLIC_PATHS = ["/", "/landing", "/login", "/demo", "/auth/callback"];

export default function AuthWrapper({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState(false);
  const [ready, setReady] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    // The session JWT lives in an httpOnly cookie (not readable here), so the
    // client-side gate uses a non-sensitive "authed" flag set at sign-in; the
    // demo workspace counts as authed for rendering. A forged flag only renders
    // the shell - every API call is still authorized server-side by the cookie.
    const isAuthed =
      localStorage.getItem("osai_authed") === "1" ||
      localStorage.getItem("osai_org_id") === "demo-org";
    setAuthed(isAuthed);
    setReady(true);

    if (!isAuthed && !PUBLIC_PATHS.includes(pathname)) {
      router.replace("/login");
    }
  }, [pathname, router]);

  // Show nothing while checking auth (avoids flash)
  if (!ready) return null;

  // Public pages render without the sidebar layout
  if (PUBLIC_PATHS.includes(pathname)) {
    return <>{children}</>;
  }

  // Not authenticated - blank while redirect fires
  if (!authed) return null;

  // Authenticated - render full app
  return <>{children}</>;
}
