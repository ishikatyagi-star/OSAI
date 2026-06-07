import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import AuthWrapper from "../components/auth-wrapper";
import Sidebar from "../components/sidebar";

export const metadata: Metadata = {
  title: "OSAI — Operating System for Company Context",
  description:
    "Connector-first operating layer for scattered company context and execution.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthWrapper>
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
                  <span style={{ fontSize: 10, padding: "2px 6px", background: "rgba(0,200,150,0.1)", color: "var(--teal)", borderRadius: 4, fontWeight: 700 }}>LIVE</span>
                </div>
              </header>
              <main>{children}</main>
            </div>
          </div>
        </AuthWrapper>
      </body>
    </html>
  );
}
