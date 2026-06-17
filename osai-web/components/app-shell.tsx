"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import Sidebar from "./sidebar";

// Pages that render without the sidebar/topbar shell
const SHELL_EXCLUDED = ["/login", "/demo"];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  // Resolve the platform-correct shortcut on the client to avoid showing the
  // Mac ⌘ to Windows/Linux users. Rendered only after mount (no hydration gap).
  const [shortcut, setShortcut] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState("");
  useEffect(() => {
    const isMac = /Mac|iPhone|iPad|iPod/i.test(navigator.userAgent);
    setShortcut(isMac ? "⌘K" : "Ctrl K");
    setWorkspace(localStorage.getItem("osai_org_name") || "Your workspace");
  }, [pathname]);

  // Make the shortcut real: ⌘/Ctrl+K jumps to the Search page.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        router.push("/search");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  const bare = SHELL_EXCLUDED.includes(pathname);
  if (bare) {
    return <>{children}</>;
  }

  // The dedicated Search page already has its own large search box, so the
  // global quick-search in the topbar is hidden there to avoid two search bars.
  const showSearch = pathname !== "/search";

  return (
    <div className="app-container">
      <Sidebar />
      <div className="dashboard-layout">
        <header className="topbar">
          {showSearch && (
            <Link href="/search" className="topbar-search" aria-label="Search the knowledge base">
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>⌕</span>
              <span className="topbar-search-text">Search knowledge base…</span>
              {shortcut && <span className="topbar-search-kbd">{shortcut}</span>}
            </Link>
          )}
          <div className="topbar-workspace">
            <span>Workspace:</span>
            <span className="topbar-workspace-name">{workspace}</span>
            <span
              style={{
                fontSize: 10,
                padding: "2px 8px",
                background: "var(--green-dim)",
                color: "var(--green)",
                borderRadius: 100,
                fontWeight: 700,
                letterSpacing: 0.3,
              }}
            >
              LIVE
            </span>
          </div>
        </header>
        <main>{children}</main>
      </div>
    </div>
  );
}
