"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import Sidebar from "./sidebar";

// Pages that render without the sidebar/topbar shell
const SHELL_EXCLUDED = ["/login", "/demo"];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const bare = SHELL_EXCLUDED.includes(pathname);

  if (bare) {
    return <>{children}</>;
  }

  return (
    <div className="app-container">
      <Sidebar />
      <div className="dashboard-layout">
        <header className="topbar">
          <div className="topbar-search">
            <span style={{ fontSize: 13, color: "var(--text-muted)" }}>⌕</span>
            <span className="topbar-search-text">Search knowledge base…</span>
            <span className="topbar-search-kbd">⌘K</span>
          </div>
          <div className="topbar-workspace">
            <span>Workspace:</span>
            <span className="topbar-workspace-name">Intellact AI</span>
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
