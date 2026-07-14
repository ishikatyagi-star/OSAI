"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import Sidebar from "./sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { clearSession, getDashboardMetrics } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import { brandText } from "@/lib/utils";

// Pages that render without the sidebar/topbar shell
const SHELL_EXCLUDED = ["/login", "/demo", "/onboarding", "/auth/callback"];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const bare = SHELL_EXCLUDED.includes(pathname);

  const [workspace, setWorkspace] = useState("");
  const [demo, setDemo] = useState(false);
  // Real connection state, so the status pill reflects reality instead of a
  // permanent "LIVE" even when nothing is connected.
  const [connected, setConnected] = useState<boolean | null>(null);
  const [connectionUnavailable, setConnectionUnavailable] = useState(false);
  const [connectionRetry, setConnectionRetry] = useState(0);
  useEffect(() => {
    if (bare) return;
    setWorkspace(brandText(localStorage.getItem("osai_org_name") || "Your workspace"));
    const demoMode = isDemo();
    setDemo(demoMode);
    if (demoMode) {
      setConnected(true);
      setConnectionUnavailable(false);
      return;
    }
    let cancelled = false;
    setConnected(null);
    setConnectionUnavailable(false);
    getDashboardMetrics(true)
      .then((m) => {
        if (!cancelled) setConnected(m.connectors_connected > 0);
      })
      .catch(() => {
        if (!cancelled) {
          setConnected(null);
          setConnectionUnavailable(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [bare, pathname, connectionRetry]);

  if (bare) {
    return <>{children}</>;
  }

  function exitDemo() {
    clearSession();
    router.replace("/");
  }

  function retryConnectionCheck() {
    setConnectionRetry((value) => value + 1);
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
                  {demo ? (
                    <span className="workspace-status workspace-status--demo">
                      DEMO
                    </span>
                  ) : connectionUnavailable ? (
                    <button
                      type="button"
                      className="workspace-status workspace-status--unavailable"
                      onClick={retryConnectionCheck}
                    >
                      RETRY STATUS
                    </button>
                  ) : connected === false ? (
                    <Link
                      href="/integrations"
                      className="workspace-status workspace-status--empty"
                    >
                      NO SOURCES
                    </Link>
                  ) : (
                    <span className="workspace-status workspace-status--live">
                      {connected === null ? "CHECKING" : "LIVE"}
                    </span>
                  )}
                </TooltipTrigger>
                <TooltipContent>
                  {demo
                    ? "Sample workspace data. Changes may reset between sessions."
                    : connectionUnavailable
                    ? "Workspace status is unavailable. Select the badge to retry."
                    : connected === false
                    ? "No connectors are connected yet - click to add a source."
                    : connected === null
                      ? "Checking connected data sources."
                      : "Your workspace is syncing data from connected tools."}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </header>
        {demo && (
          <div className="demo-workspace-banner" role="status">
            <span><strong>Demo workspace</strong> · Sample data · Changes may reset</span>
            <button type="button" onClick={exitDemo}>Exit demo</button>
          </div>
        )}
        <main>{children}</main>
      </div>
    </div>
  );
}
