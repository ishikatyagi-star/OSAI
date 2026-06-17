"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Inbox,
  LayoutDashboard,
  Plug,
  RefreshCw,
  ScrollText,
  Settings,
  Share2,
  Sparkles,
  Users,
  Zap,
  type LucideIcon,
} from "lucide-react";

type NavItem = {
  href: string;
  icon: LucideIcon;
  label: string;
  badge?: number;
};

// Decluttered IA: Search folds into Ask OSAI, Team Board folds into Decision Log,
// and Evals + Data Routing move into Settings / Integrations. One consistent icon
// set (lucide, outline, uniform stroke) so no item reads heavier than the others.
const NAV: NavItem[] = [
  { href: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/ask", icon: Sparkles, label: "Ask OSAI" },
  { href: "/inbox", icon: Inbox, label: "Context Inbox" },
  { href: "/decisions", icon: ScrollText, label: "Decision Log" },
  { href: "/graph", icon: Share2, label: "Org Graph" },
  { href: "/team", icon: Users, label: "Team" },
  { href: "/workflows", icon: Zap, label: "Workflows" },
  { href: "/integrations", icon: Plug, label: "Integrations" },
  { href: "/sync-runs", icon: RefreshCw, label: "Sync Runs" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [userName, setUserName] = useState("");
  const [orgName, setOrgName] = useState("");
  useEffect(() => {
    setUserName(localStorage.getItem("osai_user_name") || "You");
    setOrgName(localStorage.getItem("osai_org_name") || "Your workspace");
  }, []);
  const initial = (userName || "U").trim().charAt(0).toUpperCase();

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
        <Link
          href="/settings"
          className={`sidebar-nav-item${pathname.startsWith("/settings") ? " active" : ""}`}
        >
          <span className="nav-icon">
            <Settings size={16} strokeWidth={1.75} />
          </span>
          <span>Settings</span>
        </Link>
        <div className="sidebar-user">
          <div className="sidebar-avatar">{initial}</div>
          <div className="sidebar-user-info">
            <div className="sidebar-user-name">{userName}</div>
            <div className="sidebar-user-role">{orgName}</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
