"use client";

import Link from "next/link";
import { FlaskConical, Route, ChevronRight, type LucideIcon } from "lucide-react";

type SettingsLink = {
  href: string;
  icon: LucideIcon;
  title: string;
  description: string;
};

const LINKS: SettingsLink[] = [
  {
    href: "/integrations?tab=routing",
    icon: Route,
    title: "Data Routing",
    description:
      "Classify information into Normal / Amber / Red tiers and control which connectors and LLMs each tier may use. Now lives with Integrations.",
  },
  {
    href: "/settings/advanced",
    icon: FlaskConical,
    title: "Advanced · Evals",
    description:
      "Quality and regression tracking for OSAI's answers and routing. Moved out of the main nav to keep things simple.",
  },
];

export default function SettingsPage() {
  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Settings</h1>
          <p>Workspace configuration, data governance, and advanced tooling.</p>
        </div>
      </div>

      <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
        {LINKS.map((link) => {
          const Icon = link.icon;
          return (
            <Link key={link.href} href={link.href} className="card" style={{ textDecoration: "none" }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
                <div
                  className="connector-icon-badge"
                  style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
                >
                  <Icon size={18} strokeWidth={1.75} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <h2 style={{ margin: 0, fontSize: 15 }}>{link.title}</h2>
                    <ChevronRight size={14} style={{ marginLeft: "auto", color: "var(--text-muted)" }} />
                  </div>
                  <p className="meta" style={{ margin: 0, fontSize: 12, lineHeight: 1.5 }}>
                    {link.description}
                  </p>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
