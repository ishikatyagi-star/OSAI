"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();

  function isActive(path: string) {
    // Exact or prefix matching
    const active = pathname === path || (path !== "/" && pathname?.startsWith(path));
    return active ? "nav-link active" : "nav-link";
  }

  return (
    <nav className="floating-nav-capsule">
      <Link href="/integrations" className={isActive("/integrations")} id="nav-integrations">
        Integrations
      </Link>
      <span className="dot">•</span>
      <Link href="/sync-runs" className={isActive("/sync-runs")} id="nav-sync-runs">
        Sync Runs
      </Link>
      <span className="dot">•</span>
      <Link href="/" className="nav-logo">
        OSAI
      </Link>
      <span className="dot">•</span>
      <Link href="/search" className={isActive("/search")} id="nav-search">
        Search
      </Link>
      <span className="dot">•</span>
      <Link href="/workflows" className={isActive("/workflows")} id="nav-workflows">
        Workflows
      </Link>
      <span className="dot">•</span>
      <Link
        href="/settings/data-routing"
        className={isActive("/settings/data-routing")}
        id="nav-data-routing"
      >
        Routing
      </Link>
    </nav>
  );
}
