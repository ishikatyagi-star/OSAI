"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getAccessMap, type AccessMap } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import { CONNECTOR_META, getConnectorIcon } from "@/lib/connector-meta";
import { Select } from "@/components/ui/select";
import { SheldonMascot } from "@/components/sheldon-mascot";

type Tier = "normal" | "amber" | "red";

const TIER_META: Record<Tier, { label: string; color: string }> = {
  normal: { label: "Normal", color: "var(--green)" },
  amber: { label: "Amber", color: "var(--orange)" },
  red: { label: "Red", color: "var(--red)" },
};

// Small populated example for the demo/pitch view when the backend has no data.
const DEMO_ACCESS: AccessMap = {
  users: [
    { id: "u1", label: "Ishika T.", role: "admin", department: "Engineering" },
    { id: "u2", label: "Yash K.", role: "engineer", department: "Engineering" },
    { id: "u3", label: "Priya S.", role: "security", department: "Customer Support" },
    { id: "u4", label: "Anish M.", role: "analyst", department: "Product" },
  ],
  connectors: [
    { key: "notion", label: "Notion", connected: true },
    { key: "google_drive", label: "Google Drive", connected: true },
    { key: "slack", label: "Slack", connected: true },
    { key: "freshdesk", label: "Freshdesk", connected: true },
  ],
  access: [
    { user_id: "u1", connector_key: "notion", tier: "red", doc_count: 42 },
    { user_id: "u1", connector_key: "google_drive", tier: "red", doc_count: 30 },
    { user_id: "u1", connector_key: "slack", tier: "amber", doc_count: 18 },
    { user_id: "u1", connector_key: "freshdesk", tier: "amber", doc_count: 12 },
    { user_id: "u2", connector_key: "notion", tier: "amber", doc_count: 21 },
    { user_id: "u2", connector_key: "google_drive", tier: "amber", doc_count: 14 },
    { user_id: "u2", connector_key: "slack", tier: "normal", doc_count: 9 },
    { user_id: "u3", connector_key: "notion", tier: "red", doc_count: 20 },
    { user_id: "u3", connector_key: "freshdesk", tier: "red", doc_count: 8 },
    { user_id: "u4", connector_key: "notion", tier: "normal", doc_count: 11 },
    { user_id: "u4", connector_key: "slack", tier: "normal", doc_count: 6 },
  ],
};

export default function GraphPage() {
  const [data, setData] = useState<AccessMap>({ users: [], connectors: [], access: [] });
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [deptFilter, setDeptFilter] = useState<string>("all");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getAccessMap().then((res) => {
      if (cancelled) return;
      const empty = res.users.length === 0;
      setData(empty && isDemo() ? DEMO_ACCESS : res);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const roles = useMemo(
    () => Array.from(new Set(data.users.map((u) => u.role))).sort(),
    [data.users]
  );
  const depts = useMemo(
    () => Array.from(new Set(data.users.map((u) => u.department).filter(Boolean) as string[])).sort(),
    [data.users]
  );

  const visibleUsers = useMemo(
    () =>
      data.users.filter(
        (u) =>
          (roleFilter === "all" || u.role === roleFilter) &&
          (deptFilter === "all" || (u.department ?? "Unassigned") === deptFilter)
      ),
    [data.users, roleFilter, deptFilter]
  );

  // Group the visible users by department so the access map reads as an org chart
  // (the cross-department collaboration lens).
  const grouped = useMemo(() => {
    const map = new Map<string, typeof visibleUsers>();
    for (const u of visibleUsers) {
      const key = u.department ?? "Unassigned";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(u);
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [visibleUsers]);

  // Quick lookup: user_id → connector_key → access row.
  const accessByUser = useMemo(() => {
    const map = new Map<string, Map<string, AccessMap["access"][number]>>();
    for (const a of data.access) {
      if (!map.has(a.user_id)) map.set(a.user_id, new Map());
      map.get(a.user_id)!.set(a.connector_key, a);
    }
    return map;
  }, [data.access]);

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Org Graph · Access Map</h1>
          <p>
            Who can access which connected tools, and the highest data tier each person is cleared
            for. Roles without clearance for Amber or Red information simply don&apos;t see it.
          </p>
        </div>
        <div className="page-header-meta">
          <span>{visibleUsers.length} people</span>
          <span className="sep">·</span>
          <span>{data.connectors.length} tools</span>
        </div>
      </div>

      {/* Role filter + tier legend */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 18, flexWrap: "wrap" }}>
        <Select
          aria-label="Filter org graph by department"
          value={deptFilter}
          onValueChange={setDeptFilter}
          options={[
            { value: "all", label: "All departments" },
            ...depts.map((value) => ({ value, label: value })),
          ]}
        />
        <Select
          aria-label="Filter org graph by role"
          value={roleFilter}
          onValueChange={setRoleFilter}
          options={[
            { value: "all", label: "All roles" },
            ...roles.map((value) => ({ value, label: value })),
          ]}
        />
        <div style={{ display: "flex", gap: 12, marginLeft: "auto" }}>
          {(Object.keys(TIER_META) as Tier[]).map((t) => (
            <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--text-secondary)" }} className="text-micro">
              <span className={`tier-legend-dot tier-legend-dot--${t}`} />
              {TIER_META[t].label}
            </span>
          ))}
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--text-secondary)" }} className="text-micro">
            <span className="font-bold">&ndash;</span>
            No Access
          </span>
        </div>
      </div>

      {loaded && data.users.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
          <SheldonMascot state="mapping" size={104} className="empty-state-mascot" />
          <p className="text-body font-semibold" style={{ marginBottom: 6 }}>No access map yet</p>
          <p className="meta" style={{ maxWidth: 460, margin: "0 auto 16px" }}>
            The access map is built from your team members and the tools they can reach. Connect a
            source and invite your team to populate it.
          </p>
          <Link href="/integrations" className="btn btn-primary">Go to Integrations →</Link>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data-table" style={{ margin: 0 }}>
            <thead>
              <tr>
                <th style={{ width: 220 }}>Person</th>
                {data.connectors.map((c) => (
                  <th key={c.key} style={{ textAlign: "center" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      {React.createElement(getConnectorIcon(c.key), { size: 14, strokeWidth: 1.8 })}
                      {CONNECTOR_META[c.key]?.label ?? c.label}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grouped.map(([dept, deptUsers]) => (
                <React.Fragment key={dept}>
                  <tr>
                    <td
                      colSpan={data.connectors.length + 1}
                      style={{
                        background: "var(--bg-elevated)",
                        fontSize: 11,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: "0.5px",
                        color: "var(--text-secondary)",
                      }}
                    >
                      {dept} · {deptUsers.length}
                    </td>
                  </tr>
                  {deptUsers.map((u) => {
                    const row = accessByUser.get(u.id);
                    return (
                      <tr key={u.id}>
                        <td>
                          <div className="text-caption" style={{ color: "var(--text-primary)", fontWeight: 600 }}>{u.label}</div>
                          <span className="badge badge-grey" style={{ fontSize: 10 }}>{u.role}</span>
                        </td>
                        {data.connectors.map((c) => {
                          const a = row?.get(c.key);
                          if (!a) {
                            return (
                              <td key={c.key} style={{ textAlign: "center", color: "var(--text-muted)" }}>
                                <span title="No access">-</span>
                              </td>
                            );
                          }
                          const meta = TIER_META[a.tier];
                          return (
                            <td key={c.key} style={{ textAlign: "center" }}>
                              <span
                                title={`${meta.label} tier · ${a.doc_count} docs`}
                                className={`tier-badge tier-badge--${a.tier}`}
                              >
                                <span className="tier-badge-dot" />
                                {meta.label}
                              </span>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
