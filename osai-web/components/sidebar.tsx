"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FlaskConical,
  Inbox,
  LayoutDashboard,
  LayoutGrid,
  Plug,
  RefreshCw,
  Route,
  ScrollText,
  Search,
  Share2,
  Sparkles,
  Zap,
  type LucideIcon,
} from "lucide-react";

type NavItem = {
  href: string;
  icon: LucideIcon;
  label: string;
  badge?: number;
};

// One consistent icon set (lucide, outline, uniform stroke) so no item reads as
// heavier or differently styled than the others.
const NAV: NavItem[] = [
  { href: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/ask", icon: Sparkles, label: "Ask OSAI" },
  { href: "/inbox", icon: Inbox, label: "Context Inbox", badge: 8 },
  { href: "/decisions", icon: ScrollText, label: "Decision Log" },
  { href: "/board", icon: LayoutGrid, label: "Team Board", badge: 12 },
  { href: "/search", icon: Search, label: "Search" },
  { href: "/graph", icon: Share2, label: "Org Graph" },
  { href: "/workflows", icon: Zap, label: "Workflows" },
  { href: "/integrations", icon: Plug, label: "Integrations" },
  { href: "/sync-runs", icon: RefreshCw, label: "Sync Runs" },
  { href: "/evals", icon: FlaskConical, label: "Evals" },
  { href: "/settings/data-routing", icon: Route, label: "Data Routing" },
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
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`sidebar-nav-item${active ? " active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              <span className="nav-icon">
                <Icon size={16} strokeWidth={1.75} />
              </span>
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
