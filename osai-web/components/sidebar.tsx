"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Bell,
  Bookmark,
  Clock,
  LayoutDashboard,
  LogOut,
  Menu,
  Plug,
  RefreshCw,
  ScrollText,
  Settings,
  Share2,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";
import { getNotificationPage, logout } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import { NOTIFICATIONS_CHANGED_EVENT } from "@/lib/notification-events";
import { brandText } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

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

// Decluttered IA: Search folds into Ask Sheldon, Team Board folds into Decision Log,
// and Evals + Data Routing + Data (SQL sources) move into Settings / Integrations.
// The wiki is gone: you teach Sheldon a fact by telling Ask ("remember that X"),
// which writes straight to org memory. One consistent icon set (lucide, outline,
// uniform stroke) so no item reads heavier than the others.
const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { href: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
      { href: "/ask", icon: Sparkles, label: "Ask Sheldon" },
      { href: "/analytics", icon: BarChart3, label: "Analytics" },
    ],
  },
  {
    label: "Manage",
    items: [
      { href: "/decisions", icon: ScrollText, label: "Decision Log" },
      { href: "/artifacts", icon: Bookmark, label: "Artifacts" },
      { href: "/graph", icon: Share2, label: "Org Graph" },
      { href: "/team", icon: Users, label: "Team" },
      { href: "/automations", icon: Clock, label: "Automations" },
      { href: "/notifications", icon: Bell, label: "Notifications" },
    ],
  },
  {
    label: "Configure",
    items: [
      { href: "/integrations", icon: Plug, label: "Integrations" },
      { href: "/sync-runs", icon: RefreshCw, label: "Sync Runs" },
      { href: "/settings", icon: Settings, label: "Settings" },
    ],
  },
];

function navItemIsActive(pathname: string, href: string) {
  if (href === "/settings") {
    return pathname === "/settings" || pathname.startsWith("/settings/") || pathname === "/evals";
  }
  return pathname === href || (href !== "/dashboard" && pathname.startsWith(href));
}

function NavLinks({
  pathname,
  unreadCount,
  onNavigate,
}: {
  pathname: string;
  unreadCount: number;
  onNavigate?: () => void;
}) {
  return NAV_GROUPS.map((group, groupIdx) => (
    <div key={group.label}>
      {groupIdx > 0 && <div className="sidebar-group-divider" />}
      <div className="sidebar-group-label">{group.label}</div>
      {group.items.map((item) => {
        const active = navItemIsActive(pathname, item.href);
        const Icon = item.icon;
        const badge = item.href === "/notifications" ? unreadCount : item.badge;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`sidebar-nav-item${active ? " active" : ""}`}
            aria-current={active ? "page" : undefined}
            onClick={onNavigate}
          >
            <span className="nav-icon" aria-hidden="true">
              <Icon size={16} strokeWidth={1.75} />
            </span>
            <span>{item.label}</span>
            {badge ? (
              <span className="sidebar-nav-badge" aria-label={`${badge} unread notifications`}>
                {badge > 99 ? "99+" : badge}
              </span>
            ) : null}
          </Link>
        );
      })}
    </div>
  ));
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [userName, setUserName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [unreadCount, setUnreadCount] = useState(0);
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => {
    setUserName(brandText(localStorage.getItem("osai_user_name") || "You"));
    setOrgName(brandText(localStorage.getItem("osai_org_name") || "Your workspace"));
  }, []);
  useEffect(() => {
    if (isDemo()) return;
    let cancelled = false;
    const loadUnread = async () => {
      try {
        const page = await getNotificationPage(1, undefined, true, true);
        if (!cancelled) setUnreadCount(page.unread_count);
      } catch {
        // The full notifications page surfaces load failures; keep navigation usable.
      }
    };
    void loadUnread();
    const onNotificationsChanged = (event: Event) => {
      const count = (event as CustomEvent<{ unreadCount?: number }>).detail?.unreadCount;
      if (typeof count === "number") setUnreadCount(count);
      else void loadUnread();
    };
    window.addEventListener(NOTIFICATIONS_CHANGED_EVENT, onNotificationsChanged);
    const timer = window.setInterval(() => void loadUnread(), 30_000);
    return () => {
      cancelled = true;
      window.removeEventListener(NOTIFICATIONS_CHANGED_EVENT, onNotificationsChanged);
      window.clearInterval(timer);
    };
  }, []);
  const initial = (userName || "U").trim().charAt(0).toUpperCase();

  async function handleSignOut() {
    try {
      await logout();
    } catch {
      // Local session state is cleared by logout() even when the server is
      // unreachable. Avoid an unhandled event-handler rejection on the way out.
    } finally {
      router.replace("/login");
    }
  }

  return (
    <>
      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogTrigger asChild>
          <button
            type="button"
            className="mobile-nav-trigger"
            aria-label="Open navigation"
          >
            <Menu size={20} aria-hidden="true" />
          </button>
        </DialogTrigger>
        <DialogContent className="mobile-nav-panel left-0 top-0 translate-x-0 translate-y-0">
          <DialogTitle className="sr-only">Navigation</DialogTitle>
          <DialogDescription className="sr-only">
            Navigate between Sheldon workspace pages.
          </DialogDescription>
          <Link
            href="/dashboard"
            className="mobile-nav-brand"
            aria-label="Sheldon home"
            onClick={() => setMobileOpen(false)}
          >
            <Image
              src="/brand/sheldon-ai-logo.png"
              alt=""
              width={30}
              height={30}
              className="sidebar-logo-mark"
              priority
            />
            <span>Sheldon</span>
          </Link>
          <nav className="mobile-nav-list" aria-label="Primary navigation">
            <NavLinks pathname={pathname} unreadCount={unreadCount} onNavigate={() => setMobileOpen(false)} />
          </nav>
          <div className="mobile-nav-footer">
            <div>
              <strong>{userName}</strong>
              <span>{orgName}</span>
            </div>
            <button type="button" onClick={handleSignOut} className="sidebar-profile-action">
              <LogOut size={16} strokeWidth={1.75} aria-hidden="true" />
              <span>Sign out</span>
            </button>
          </div>
        </DialogContent>
      </Dialog>

      <aside className="sidebar">
      {/* Logo */}
      <Link href="/dashboard" className="sidebar-logo" aria-label="Sheldon home">
        <Image
          src="/brand/sheldon-ai-logo.png"
          alt=""
          width={28}
          height={28}
          className="sidebar-logo-mark"
          priority
        />
        <div>
          <span className="sidebar-logo-text">Sheldon</span>
        </div>
      </Link>

      {/* Nav */}
      <nav className="sidebar-nav" aria-label="Primary navigation">
        <NavLinks pathname={pathname} unreadCount={unreadCount} />
      </nav>

      {/* Footer */}
      <div className="sidebar-footer">
        <details className="sidebar-profile-menu">
          <summary className="sidebar-user" aria-label={`${userName || "User"} profile menu`}>
            <div className="sidebar-avatar">{initial}</div>
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">{userName}</div>
              <div className="sidebar-user-role">{orgName}</div>
            </div>
          </summary>
          <div className="sidebar-profile-popover">
            <Link href="/settings" className="sidebar-profile-action">
              <Settings size={16} strokeWidth={1.75} />
              <span>Settings</span>
            </Link>
            <button type="button" onClick={handleSignOut} className="sidebar-profile-action">
              <LogOut size={16} strokeWidth={1.75} />
              <span>Sign out</span>
            </button>
          </div>
        </details>
      </div>
      </aside>
    </>
  );
}
