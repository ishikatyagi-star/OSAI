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
import { isDemo } from "@/lib/demo";
import { DEMO_DEPARTMENTS, DEMO_TEAM_MEMBERS } from "@/lib/demo-data";
import { Select } from "@/components/ui/select";
import { brandText } from "@/lib/utils";

function writeErrorMessage(err: unknown): string {
  if (isDemo()) return "Team changes aren't available in the shared demo workspace - sign in with Google to manage a real team.";
  if (err instanceof Error && err.message.includes("(401)"))
    return "Your session doesn't allow this change. Try signing in again.";
  return "Couldn't save this change - please try again.";
}

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
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [loadWarning, setLoadWarning] = useState("");

  const refresh = useCallback(async () => {
    if (isDemo()) {
      setMembers(DEMO_TEAM_MEMBERS);
      setDepartments(DEMO_DEPARTMENTS);
      setInvites([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError("");
    setLoadWarning("");
    try {
      const [membersResult, departmentsResult, invitesResult] = await Promise.allSettled([
        getTeamMembers(true),
        getDepartments(true),
        getInvites(true),
      ]);
      if (membersResult.status === "rejected" || departmentsResult.status === "rejected") {
        throw new Error("Core team data unavailable");
      }
      setMembers(membersResult.value);
      setDepartments(departmentsResult.value);
      if (invitesResult.status === "fulfilled") {
        setInvites(invitesResult.value);
      } else {
        setInvites([]);
        setLoadWarning("Members and departments loaded, but pending invites are temporarily unavailable.");
      }
    } catch {
      setLoadError("Team data could not be loaded. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  // Invite form
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviteDept, setInviteDept] = useState("");
  const [inviteTier, setInviteTier] = useState("normal");
  const [inviting, setInviting] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  // Department form
  const [deptName, setDeptName] = useState("");
  const [addingDepartment, setAddingDepartment] = useState(false);

  // Inline write-failure message. Writes are admin-gated on the backend, so
  // they 401 in the demo workspace - that must never eject the session.
  const [writeError, setWriteError] = useState("");

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!inviteEmail.trim() || inviting) return;
    if (isDemo()) {
      setWriteError(writeErrorMessage(null));
      return;
    }
    setInviting(true);
    setWriteError("");
    try {
      const invite = await createInvite(
        inviteEmail.trim(),
        inviteRole,
        inviteDept || null,
        inviteRole === "admin" ? "red" : inviteTier
      );
      setInviteEmail("");
      setInviteDept("");
      setInviteTier("normal");
      setInvites((current) => [invite, ...current.filter((item) => item.id !== invite.id)]);
    } catch (err) {
      setWriteError(writeErrorMessage(err));
    } finally {
      setInviting(false);
    }
  }

  async function handleAddDept(e: React.FormEvent) {
    e.preventDefault();
    if (!deptName.trim() || addingDepartment) return;
    if (isDemo()) {
      setWriteError(writeErrorMessage(null));
      return;
    }
    setAddingDepartment(true);
    setWriteError("");
    try {
      const department = await createDepartment(deptName.trim());
      setDeptName("");
      setDepartments((current) => [...current.filter((item) => item.id !== department.id), department]);
    } catch (err) {
      setWriteError(writeErrorMessage(err));
    } finally {
      setAddingDepartment(false);
    }
  }

  async function changeMember(
    m: TeamMember,
    patch: { role?: string; department_id?: string | null; data_tier?: string }
  ) {
    if (isDemo()) {
      setWriteError(writeErrorMessage(null));
      return;
    }
    setMembers((prev) => prev.map((x) => (x.id === m.id ? { ...x, ...patch } : x)));
    setWriteError("");
    try {
      await updateMember(m.id, patch);
    } catch (err) {
      setWriteError(writeErrorMessage(err));
    }
    refresh();
  }

  async function copyLink(link: string) {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(link);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      setWriteError("Couldn't copy the invite link. Select and copy it manually.");
    }
  }

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, current: Tab) {
    const keys: Tab[] = ["members", "departments", "invites"];
    const index = keys.indexOf(current);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % keys.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + keys.length) % keys.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = keys.length - 1;
    else return;
    event.preventDefault();
    const nextTab = keys[next];
    setTab(nextTab);
    requestAnimationFrame(() => document.getElementById(`team-tab-${nextTab}`)?.focus());
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
      <div className="tabs-underline" role="tablist" aria-label="Team sections">
        {([
          { key: "members", label: `Members (${members.length})` },
          { key: "departments", label: `Departments (${departments.length})` },
          { key: "invites", label: `Invites (${invites.length})` },
        ] as const).map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key as Tab)}
            onKeyDown={(event) => handleTabKeyDown(event, t.key)}
            className={`tabs-underline-trigger${tab === t.key ? ' active' : ''}`}
            role="tab"
            id={`team-tab-${t.key}`}
            aria-controls={`team-panel-${t.key}`}
            aria-selected={tab === t.key}
            tabIndex={tab === t.key ? 0 : -1}
          >
            {t.label}
          </button>
        ))}
      </div>

      {writeError && (
        <div
          className="card"
          role="alert"
          style={{ marginBottom: 16, padding: "10px 14px", color: "var(--yellow)", fontSize: 13 }}
        >
          {writeError}
        </div>
      )}

      {loadError && !loading && (
        <div className="card async-state" role="alert">
          <div>
            <p className="error-text" style={{ marginBottom: 12 }}>{loadError}</p>
            <button type="button" className="btn btn-primary" onClick={refresh}>Retry</button>
          </div>
        </div>
      )}

      {loading && (
        <div className="card async-state" role="status" aria-live="polite">
          Loading team…
        </div>
      )}

      {loadWarning && !loading && !loadError && (
        <div className="card" role="status" style={{ marginBottom: 16, padding: "12px 16px" }}>
          {loadWarning}
        </div>
      )}

      {/* MEMBERS */}
      {!loading && !loadError && tab === "members" && (
        <div className="table-scroll" tabIndex={0} role="tabpanel" id="team-panel-members" aria-labelledby="team-tab-members">
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
                    {brandText(m.display_name)}
                  </div>
                  <div className="meta">{m.email}</div>
                </td>
                <td>
                  <Select
                    aria-label={`Role for ${brandText(m.display_name)}`}
                    style={{ height: 30 }}
                    value={m.role}
                    onValueChange={(value) => changeMember(m, { role: value })}
                    options={ROLES.map((value) => ({ value, label: value }))}
                  />
                </td>
                <td>
                  <Select
                    aria-label={`Department for ${brandText(m.display_name)}`}
                    style={{ height: 30 }}
                    value={m.department_id ?? "unassigned"}
                    onValueChange={(value) => changeMember(m, { department_id: value === "unassigned" ? null : value })}
                    options={[
                      { value: "unassigned", label: "- Unassigned -" },
                      ...departments.map((department) => ({ value: department.id, label: department.name })),
                    ]}
                  />
                </td>
                <td>
                  {m.role === "admin" ? (
                    <span className="badge badge-purple" title="Admins see all data tiers">
                      All (admin)
                    </span>
                  ) : (
                    <Select
                      aria-label={`Data access for ${brandText(m.display_name)}`}
                      style={{ height: 30 }}
                      value={m.data_tier}
                      onValueChange={(value) => changeMember(m, { data_tier: value })}
                      options={TIERS.map((value) => ({ value, label: TIER_LABEL[value] }))}
                    />
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
        </div>
      )}

      {/* DEPARTMENTS */}
      {!loading && !loadError && tab === "departments" && (
        <div role="tabpanel" id="team-panel-departments" aria-labelledby="team-tab-departments">
          <form onSubmit={handleAddDept} style={{ display: "flex", gap: 8, marginBottom: 18, maxWidth: 420 }}>
            <label className="sr-only" htmlFor="new-department-name">New department name</label>
            <input id="new-department-name" name="department" className="search-input" placeholder="New department name…" required value={deptName} onChange={(e) => setDeptName(e.target.value)} disabled={addingDepartment} />
            <button type="submit" className="btn btn-primary" style={{ whiteSpace: "nowrap" }} disabled={addingDepartment || !deptName.trim()}>
              <Plus className="size-3.5" /> {addingDepartment ? "Addingâ€¦" : "Add"}
            </button>
          </form>
          <div className="card-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}>
            {departments.map((d) => (
              <div key={d.id} className="card" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ width: 10, height: 10, borderRadius: "50%", background: d.color }} />
                <div style={{ flex: 1 }}>
                  <div className="font-semibold">{brandText(d.name)}</div>
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
      {!loading && !loadError && tab === "invites" && (
        <div role="tabpanel" id="team-panel-invites" aria-labelledby="team-tab-invites">
          <form
            onSubmit={handleInvite}
            className="card"
            style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 20 }}
          >
            <div style={{ flex: 1, minWidth: 220 }}>
              <label htmlFor="invite-email" className="meta" style={{ display: "block", marginBottom: 4 }}>Work email</label>
              <input
                id="invite-email"
                name="email"
                className="search-input"
                type="email"
                autoComplete="email"
                required
                placeholder="teammate@company.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                style={{ width: "100%" }}
              />
            </div>
            <div>
              <label className="meta" style={{ display: "block", marginBottom: 4 }}>Role</label>
              <Select
                aria-label="Invite role"
                value={inviteRole}
                onValueChange={setInviteRole}
                options={ROLES.map((value) => ({ value, label: value }))}
              />
            </div>
            <div>
              <label className="meta" style={{ display: "block", marginBottom: 4 }}>Data access</label>
              <Select
                aria-label="Invite data access"
                value={inviteRole === "admin" ? "red" : inviteTier}
                disabled={inviteRole === "admin"}
                onValueChange={setInviteTier}
                title={inviteRole === "admin" ? "Admins see all data tiers" : "Highest data tier this member can see"}
                options={TIERS.map((value) => ({ value, label: TIER_LABEL[value] }))}
              />
            </div>
            <div>
              <label className="meta" style={{ display: "block", marginBottom: 4 }}>Department</label>
              <Select
                aria-label="Invite department"
                value={inviteDept || "none"}
                onValueChange={(value) => setInviteDept(value === "none" ? "" : value)}
                options={[
                  { value: "none", label: "- None -" },
                  ...departments.map((department) => ({ value: department.id, label: department.name })),
                ]}
              />
            </div>
            <button type="submit" className="btn btn-primary" disabled={inviting || !inviteEmail.trim()}>
              {inviting ? "Inviting…" : "Send invite"}
            </button>
          </form>

          <p className="meta" style={{ marginBottom: 12 }}>
            Share the invite link with the teammate. When they sign in with Google using that email,
            they join this workspace with the role and department you set.
          </p>

          <div className="table-scroll" tabIndex={0} role="region" aria-label="Pending team invitations">
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
                  <td colSpan={4} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px 16px" }}>
                    No pending invites.
                  </td>
                </tr>
              )}
            </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
