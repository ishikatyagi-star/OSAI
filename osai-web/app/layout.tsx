import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "OSAI",
  description: "Connector-first operating layer for scattered company context."
};

const navItems = [
  ["/integrations", "Integrations"],
  ["/sync-runs", "Sync Runs"],
  ["/search", "Search"],
  ["/workflows", "Workflows"],
  ["/settings/data-routing", "Data Routing"]
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <aside className="sidebar">
            <div className="brand">OSAI</div>
            <nav className="nav" aria-label="Primary navigation">
              {navItems.map(([href, label]) => (
                <Link key={href} href={href}>
                  {label}
                </Link>
              ))}
            </nav>
          </aside>
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
