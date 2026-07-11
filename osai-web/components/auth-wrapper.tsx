"use client";

import { useState, useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

// Pages that don't require authentication (handled by route handlers or their own UI)
const PUBLIC_PATHS = ["/", "/landing", "/login", "/demo", "/auth/callback"];

export default function AuthWrapper({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    const savedToken = localStorage.getItem("osai_token");
    setToken(savedToken);
    setReady(true);

    if (!savedToken && !PUBLIC_PATHS.includes(pathname)) {
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
  if (!token) return null;

  // Authenticated - render full app
  return <>{children}</>;
}
