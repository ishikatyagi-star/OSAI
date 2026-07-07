"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import Sidebar from "./sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getDashboardMetrics } from "@/lib/api";
import { isDemo } from "@/lib/demo";

// Pages that render without the sidebar/topbar shell
const SHELL_EXCLUDED = ["/login", "/demo"];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  const [workspace, setWorkspace] = useState("");
  // Real connection state, so the status pill reflects reality instead of a
  // permanent "LIVE" even when nothing is connected.
  const [connected, setConnected] = useState<boolean | null>(null);
  useEffect(() => {
    setWorkspace(localStorage.getItem("osai_org_name") || "Your workspace");
    if (isDemo()) {
      setConnected(true);
      return;
    }
    getDashboardMetrics()
      .then((m) => setConnected(m.connectors_connected > 0))
      .catch(() => setConnected(false));
  }, [pathname]);

  const bare = SHELL_EXCLUDED.includes(pathname);
  if (bare) {
    return <>{children}</>;
  }

  return (
    <div className="app-container">
      <Sidebar />
      <div className="dashboard-layout">
        <header className="topbar">
          <div className="topbar-workspace">
            <span>Workspace:</span>
            <span className="topbar-workspace-name">{workspace}</span>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  {connected === false ? (
                    <Link
                      href="/integrations"
                      style={{
                        fontSize: 10,
                        padding: "2px 8px",
                        background: "var(--bg-elevated)",
                        color: "var(--text-secondary)",
                        borderRadius: 100,
                        fontWeight: 700,
                        letterSpacing: 0.3,
                        textDecoration: "none",
                      }}
                    >
                      NO SOURCES
                    </Link>
                  ) : (
                    <span
                      style={{
                        fontSize: 10,
                        padding: "2px 8px",
                        background: "var(--green-dim)",
                        color: "var(--green)",
                        borderRadius: 100,
                        fontWeight: 700,
                        letterSpacing: 0.3,
                        opacity: connected === null ? 0.5 : 1,
                      }}
                    >
                      LIVE
                    </span>
                  )}
                </TooltipTrigger>
                <TooltipContent>
                  {connected === false
                    ? "No connectors are connected yet — click to add a source."
                    : "Your workspace is syncing data from connected tools."}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </header>
        <main>{children}</main>
      </div>
    </div>
  );
}
