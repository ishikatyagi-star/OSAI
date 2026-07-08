"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Check, Plus } from "lucide-react";
import {
  createDepartment,
  createInvite,
  getDepartments,
  getInvites,
  getTeamMembers,
  updateMember,
  type Department,
  type TeamInvite,
  type TeamMember,
} from "@/lib/api";

type Tab = "members" | "departments" | "invites";
const ROLES = ["admin", "manager", "member"] as const;
const TIERS = ["normal", "amber", "red"] as const;

const ROLE_BADGE: Record<string, string> = {
  admin: "badge-purple",
  manager: "badge-amber",
  member: "badge-grey",
};

const TIER_BADGE: Record<string, string> = {
  normal: "badge-grey",
  amber: "badge-amber",
  red: "badge-red",
};

const TIER_LABEL: Record<string, string> = {
  normal: "Normal",
  amber: "Amber",
  red: "Red (full)",
};

export default function TeamPage() {
  const [tab, setTab] = useState<Tab>("members");
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [invites, setInvites] = useState<TeamInvite[]>([]);

  const refresh = useCallback(() => {
    getTeamMembers().then(setMembers);
    getDepartments().then(setDepartments);
    getInvites().then(setInvites);
  }, []);
  useEffect(() => refresh(), [refresh]);

  // Invite form
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviteDept, setInviteDept] = useState("");
  const [inviteTier, setInviteTier] = useState("normal");
  const [inviting, setInviting] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  // Department form
  const [deptName, setDeptName] = useState("");

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setInviting(true);
    try {
      await createInvite(inviteEmail.trim(), inviteRole, inviteDept || null, inviteTier);
      setInviteEmail("");
      setInviteDept("");
      setInviteTier("normal");
      getInvites().then(setInvites);
    } finally {
      setInviting(false);
    }
  }

  async function handleAddDept(e: React.FormEvent) {
    e.preventDefault();
    if (!deptName.trim()) return;
    await createDepartment(deptName.trim());
    setDeptName("");
    getDepartments().then(setDepartments);
  }

  async function changeMember(
    m: TeamMember,
    patch: { role?: string; department_id?: string | null; data_tier?: string }
  ) {
    setMembers((prev) => prev.map((x) => (x.id === m.id ? { ...x, ...patch } : x)));
    await updateMember(m.id, patch);
    refresh();
  }

  function copyLink(link: string) {
    navigator.clipboard?.writeText(link);
    setCopied(link);
    setTimeout(() => setCopied(null), 2000);
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-header-left">
          <h1>Team</h1>
          <p>
            Invite employees, assign roles and data-access tiers, and organize them into
            departments. A member only sees documents at or below their tier; admins see all.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="tabs-underline">
        {([
          { key: "members", label: `Members (${members.length})` },
          { key: "departments", label: `Departments (${departments.length})` },
          { key: "invites", label: `Invites (${invites.length})` },
        ] as const).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key as Tab)}
            className={`tabs-underline-trigger${tab === t.key ? ' active' : ''}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* MEMBERS */}
      {tab === "members" && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Member</th>
              <th style={{ width: 140 }}>Role</th>
              <th style={{ width: 200 }}>Department</th>
              <th style={{ width: 150 }}>Data access</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id}>
                <td>
                  <div className="text-caption" style={{ color: "var(--text-primary)", fontWeight: 600 }}>
                    {m.display_name}
                  </div>
                  <div className="meta">{m.email}</div>
                </td>
                <td>
                  <select
                    className="select"
                    style={{ height: 30 }}
                    value={m.role}
                    onChange={(e) => changeMember(m, { role: e.target.value })}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    className="select"
                    style={{ height: 30 }}
                    value={m.department_id ?? ""}
                    onChange={(e) => changeMember(m, { department_id: e.target.value || null })}
                  >
                    <option value="">— Unassigned —</option>
                    {departments.map((d) => (
                      <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                  </select>
                </td>
                <td>
                  {m.role === "admin" ? (
                    <span className="badge badge-purple" title="Admins see all data tiers">
                      All (admin)
                    </span>
                  ) : (
                    <select
                      className="select"
                      style={{ height: 30 }}
                      value={m.data_tier}
                      onChange={(e) => changeMember(m, { data_tier: e.target.value })}
                    >
                      {TIERS.map((t) => (
                        <option key={t} value={t}>{TIER_LABEL[t]}</option>
                      ))}
                    </select>
                  )}
                </td>
              </tr>
            ))}
            {members.length === 0 && (
              <tr>
                <td colSpan={4} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px 16px" }}>
                  No members yet. Invite teammates from the Invites tab.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {/* DEPARTMENTS */}
      {tab === "departments" && (
        <div>
          <form onSubmit={handleAddDept} style={{ display: "flex", gap: 8, marginBottom: 18, maxWidth: 420 }}>
            <input
              className="search-input"
              placeholder="New department name…"
              value={deptName}
              onChange={(e) => setDeptName(e.target.value)}
            />
            <button type="submit" className="btn btn-primary" style={{ whiteSpace: "nowrap" }}>
              <Plus className="size-3.5" /> Add
            </button>
          </form>
          <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}>
            {departments.map((d) => (
              <div key={d.id} className="card" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ width: 10, height: 10, borderRadius: "50%", background: d.color }} />
                <div style={{ flex: 1 }}>
                  <div className="font-semibold">{d.name}</div>
                  <div className="meta">
                    {d.members} member{d.members === 1 ? "" : "s"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* INVITES */}
      {tab === "invites" && (
        <div>
          <form
            onSubmit={handleInvite}
            className="card"
            style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 20 }}
          >
            <div style={{ flex: 1, minWidth: 220 }}>
              <label className="meta" style={{ display: "block", marginBottom: 4 }}>Work email</label>
              <input
                className="search-input"
                type="email"
                placeholder="teammate@company.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                style={{ width: "100%" }}
              />
            </div>
            <div>
              <label className="meta" style={{ display: "block", marginBottom: 4 }}>Role</label>
              <select className="select" value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className="meta" style={{ display: "block", marginBottom: 4 }}>Data access</label>
              <select
                className="select"
                value={inviteRole === "admin" ? "red" : inviteTier}
                disabled={inviteRole === "admin"}
                onChange={(e) => setInviteTier(e.target.value)}
                title={inviteRole === "admin" ? "Admins see all data tiers" : "Highest data tier this member can see"}
              >
                {TIERS.map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}
              </select>
            </div>
            <div>
              <label className="meta" style={{ display: "block", marginBottom: 4 }}>Department</label>
              <select className="select" value={inviteDept} onChange={(e) => setInviteDept(e.target.value)}>
                <option value="">— None —</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <button type="submit" className="btn btn-primary" disabled={inviting}>
              {inviting ? "Inviting…" : "Send invite"}
            </button>
          </form>

          <p className="meta" style={{ marginBottom: 12 }}>
            Share the invite link with the teammate. When they sign in with Google using that email,
            they join this workspace with the role and department you set.
          </p>

          <table className="data-table">
            <thead>
              <tr>
                <th>Email</th>
                <th style={{ width: 110 }}>Role</th>
                <th style={{ width: 120 }}>Data access</th>
                <th style={{ width: 160 }}>Invite link</th>
              </tr>
            </thead>
            <tbody>
              {invites.map((i) => (
                <tr key={i.id}>
                  <td>{i.email}</td>
                  <td><span className={`badge ${ROLE_BADGE[i.role] ?? "badge-grey"}`}>{i.role}</span></td>
                  <td>
                    <span className={`badge ${TIER_BADGE[i.role === "admin" ? "red" : i.data_tier] ?? "badge-grey"}`}>
                      {i.role === "admin" ? "All" : TIER_LABEL[i.data_tier] ?? i.data_tier}
                    </span>
                  </td>
                  <td>
                    <button
                      className="btn"
                      style={{ fontSize: 11, padding: "4px 10px" }}
                      onClick={() => copyLink(i.invite_link)}
                    >
                      {copied === i.invite_link ? (
                        <><Check className="size-3.5" /> Copied</>
                      ) : (
                        <><Copy className="size-3.5" /> Copy link</>
                      )}
                    </button>
                  </td>
                </tr>
              ))}
              {invites.length === 0 && (
                <tr>
                  <td colSpan={3} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px 16px" }}>
                    No pending invites.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
