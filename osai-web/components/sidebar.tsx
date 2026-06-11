"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/dashboard", icon: "◈", label: "Dashboard" },
  { href: "/ask", icon: "✦", label: "Ask OSAI" },
  { href: "/inbox", icon: "⬡", label: "Context Inbox", badge: 8 },
  { href: "/decisions", icon: "◎", label: "Decision Log" },
  { href: "/board", icon: "▦", label: "Team Board", badge: 12 },
  { href: "/search", icon: "⌕", label: "Search" },
  { href: "/graph", icon: "◍", label: "Org Graph" },
  { href: "/workflows", icon: "⚡", label: "Workflows" },
  { href: "/integrations", icon: "⬡", label: "Integrations" },
  { href: "/sync-runs", icon: "↻", label: "Sync Runs" },
  { href: "/evals", icon: "▤", label: "Evals" },
  { href: "/settings/data-routing", icon: "⊞", label: "Data Routing" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      {/* Logo */}
      <Link href="/dashboard" className="sidebar-logo">
        <div className="sidebar-logo-mark">O</div>
        <div>
          <span className="sidebar-logo-text">OSAI</span>
          <span className="sidebar-logo-version"> v1</span>
        </div>
      </Link>

      {/* Nav */}
      <nav className="sidebar-nav">
        {NAV.map((item) => {
          const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`sidebar-nav-item${active ? " active" : ""}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
              {item.badge && (
                <span className="sidebar-nav-badge">{item.badge}</span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="sidebar-avatar">A</div>
          <div className="sidebar-user-info">
            <div className="sidebar-user-name">Admin</div>
            <div className="sidebar-user-role">Intellact AI</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
