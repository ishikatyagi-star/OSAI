"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Clock,
  Inbox,
  LayoutDashboard,
  LogOut,
  Plug,
  RefreshCw,
  ScrollText,
  Settings,
  Share2,
  Sparkles,
  Trash2,
  Users,
  type LucideIcon,
} from "lucide-react";
import { clearSession, deleteAccount } from "@/lib/api";

type NavItem = {
  href: string;
  icon: LucideIcon;
  label: string;
  badge?: number;
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

// Decluttered IA: Search folds into Ask OSAI, Team Board folds into Decision Log,
// and Evals + Data Routing move into Settings / Integrations. One consistent icon
// set (lucide, outline, uniform stroke) so no item reads heavier than the others.
const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { href: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
      { href: "/ask", icon: Sparkles, label: "Ask OSAI" },
      { href: "/dashboards", icon: BarChart3, label: "Analytics" },
    ],
  },
  {
    label: "Manage",
    items: [
      { href: "/inbox", icon: Inbox, label: "Context Inbox" },
      { href: "/decisions", icon: ScrollText, label: "Decision Log" },
      { href: "/graph", icon: Share2, label: "Org Graph" },
      { href: "/team", icon: Users, label: "Team" },
      { href: "/automations", icon: Clock, label: "Automations" },
    ],
  },
  {
    label: "Configure",
    items: [
      { href: "/integrations", icon: Plug, label: "Integrations" },
      { href: "/sync-runs", icon: RefreshCw, label: "Sync Runs" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [userName, setUserName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    setUserName(localStorage.getItem("osai_user_name") || "You");
    setOrgName(localStorage.getItem("osai_org_name") || "Your workspace");
  }, []);
  const initial = (userName || "U").trim().charAt(0).toUpperCase();

  function handleSignOut() {
    clearSession();
    router.replace("/login");
  }

  async function handleDeleteAccount() {
    if (
      !window.confirm(
        "Permanently delete your account? This cannot be undone. You'll be signed out."
      )
    ) {
      return;
    }
    setDeleting(true);
    try {
      await deleteAccount();
    } catch {
      // Even if the server call fails (e.g. demo token), clear the local session
      // so the user isn't stuck in a half-signed-in state.
      clearSession();
    } finally {
      router.replace("/login");
    }
  }

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
        {NAV_GROUPS.map((group, groupIdx) => (
          <div key={group.label}>
            {groupIdx > 0 && <div className="sidebar-group-divider" />}
            <div className="sidebar-group-label">{group.label}</div>
            {group.items.map((item) => {
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
          </div>
        ))}
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
        <button
          type="button"
          onClick={handleSignOut}
          className="sidebar-nav-item"
          style={{ width: "100%", background: "none", border: "none", cursor: "pointer" }}
        >
          <span className="nav-icon">
            <LogOut size={16} strokeWidth={1.75} />
          </span>
          <span>Sign out</span>
        </button>
        <button
          type="button"
          onClick={handleDeleteAccount}
          disabled={deleting}
          className="sidebar-nav-item"
          style={{
            width: "100%",
            background: "none",
            border: "none",
            cursor: deleting ? "default" : "pointer",
            color: "var(--red)",
          }}
        >
          <span className="nav-icon">
            <Trash2 size={16} strokeWidth={1.75} />
          </span>
          <span>{deleting ? "Deleting…" : "Delete account"}</span>
        </button>
      </div>
    </aside>
  );
}
