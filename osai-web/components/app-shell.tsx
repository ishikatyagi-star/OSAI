"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import Sidebar from "./sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// Pages that render without the sidebar/topbar shell
const SHELL_EXCLUDED = ["/login", "/demo"];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  const [workspace, setWorkspace] = useState("");
  useEffect(() => {
    setWorkspace(localStorage.getItem("osai_org_name") || "Your workspace");
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
                </TooltipTrigger>
                <TooltipContent>
                  Your workspace is actively syncing data from connected tools.
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
