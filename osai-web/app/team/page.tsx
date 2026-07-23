"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Check, Pencil, Plus, Trash2, UserMinus } from "lucide-react";
import {
  createDepartment,
  createInvite,
  getDepartments,
  getInvites,
  getMemberRemovalImpact,
  getSession,
  getTeamMembers,
  removeDepartment,
  removeTeamMember,
  renameDepartment,
  revokeInvite,
  updateMember,
  type Department,
  type MemberRemovalImpact,
  type TeamInvite,
  type TeamMember,
} from "@/lib/api";
import { isDemo } from "@/lib/demo";
import { DEMO_DEPARTMENTS, DEMO_TEAM_MEMBERS } from "@/lib/demo-data";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { brandText } from "@/lib/utils";

function writeErrorMessage(err: unknown): string {
  if (isDemo()) return "Team changes aren't available in the shared demo workspace - sign in with Google to manage a real team.";
  if (err instanceof Error) {
    if (err.message.includes("(401)"))
      return "Your session doesn't allow this change. Try signing in again.";
    const detail = err.message.match(/"detail":"([^"]+)"/)?.[1];
    if (detail) return detail;
    const structuredMessage = err.message.match(/"message":"([^"]+)"/)?.[1];
    if (structuredMessage) return structuredMessage;
  }
  return "Couldn't save this change - please try again.";
}

type Tab = "members" | "departments" | "invites";
const ROLES = ["admin", "member"] as const;
const TIERS = ["normal", "amber", "red"] as const;

const ROLE_BADGE: Record<string, string> = {
  admin: "badge-purple",
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
  const [isAdmin, setIsAdmin] = useState(false);
  const [currentUserId, setCurrentUserId] = useState("");

  const refresh = useCallback(async (includeInvites = false) => {
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
        includeInvites ? getInvites(true) : Promise.resolve([]),
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
  useEffect(() => {
    if (isDemo()) {
      void refresh();
      return;
    }
    getSession(true)
      .then((session) => {
        const admin = !!session?.is_admin;
        setIsAdmin(admin);
        setCurrentUserId(session?.user_id ?? "");
        return refresh(admin);
      })
      .catch(() => void refresh(false));
  }, [refresh]);

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
  const [actionBusy, setActionBusy] = useState("");
  const [removalMember, setRemovalMember] = useState<TeamMember | null>(null);
  const [removalImpact, setRemovalImpact] = useState<MemberRemovalImpact | null>(null);
  const [removalLoading, setRemovalLoading] = useState(false);
  const [removalError, setRemovalError] = useState("");
  const [transferTargetId, setTransferTargetId] = useState("");

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
      if (m.id === currentUserId && patch.role !== undefined) {
        const session = await getSession(true).catch(() => null);
        const admin = !!session?.is_admin;
        setIsAdmin(admin);
        setCurrentUserId(session?.user_id ?? "");
        if (!admin) {
          setInvites([]);
          setTab("members");
        }
        await refresh(admin);
        return;
      }
    } catch (err) {
      setWriteError(writeErrorMessage(err));
    }
    await refresh(isAdmin);
  }

  async function handleRemoveMember(member: TeamMember) {
    if (isDemo()) {
      setWriteError(writeErrorMessage(null));
      return;
    }
    setRemovalMember(member);
    setRemovalImpact(null);
    setRemovalError("");
    setTransferTargetId("");
    setRemovalLoading(true);
    setWriteError("");
    try {
      const impact = await getMemberRemovalImpact(member.id, true);
      if (!impact) throw new Error("Member removal impact is unavailable.");
      setRemovalImpact(impact);
    } catch (err) {
      setRemovalError(writeErrorMessage(err));
    } finally {
      setRemovalLoading(false);
    }
  }

  async function confirmRemoveMember() {
    const member = removalMember;
    const impact = removalImpact;
    if (!member || !impact || actionBusy) return;
    if (impact.requires_transfer && !transferTargetId) {
      setRemovalError("Choose a workspace member to receive these assets.");
      return;
    }
    setActionBusy(`member:${member.id}`);
    setRemovalError("");
    setWriteError("");
    try {
      await removeTeamMember(
        member.id,
        impact.requires_transfer ? transferTargetId : undefined
      );
      setMembers((current) => current.filter((item) => item.id !== member.id));
      if (member.department_id) {
        setDepartments((current) => current.map((department) =>
          department.id === member.department_id
            ? { ...department, members: Math.max(0, department.members - 1) }
            : department
        ));
      }
      setRemovalMember(null);
      setRemovalImpact(null);
      setTransferTargetId("");
    } catch (err) {
      setRemovalError(writeErrorMessage(err));
    } finally {
      setActionBusy("");
    }
  }

  function closeRemovalDialog() {
    if (actionBusy.startsWith("member:")) return;
    setRemovalMember(null);
    setRemovalImpact(null);
    setRemovalError("");
    setTransferTargetId("");
  }

  async function handleRenameDepartment(department: Department) {
    const name = window.prompt("Rename department", department.name)?.trim();
    if (!name || name === department.name) return;
    setActionBusy(`department:${department.id}`);
    setWriteError("");
    try {
      const updated = await renameDepartment(department.id, name);
      setDepartments((current) => current.map((item) =>
        item.id === department.id ? { ...item, ...updated } : item
      ));
    } catch (err) {
      setWriteError(writeErrorMessage(err));
    } finally {
      setActionBusy("");
    }
  }

  async function handleRemoveDepartment(department: Department) {
    if (!window.confirm(`Delete the ${department.name} department?`)) return;
    setActionBusy(`department:${department.id}`);
    setWriteError("");
    try {
      await removeDepartment(department.id);
      setDepartments((current) => current.filter((item) => item.id !== department.id));
    } catch (err) {
      setWriteError(writeErrorMessage(err));
    } finally {
      setActionBusy("");
    }
  }

  async function handleRevokeInvite(invite: TeamInvite) {
    if (!window.confirm(`Revoke the invite link for ${invite.email}?`)) return;
    setActionBusy(`invite:${invite.id}`);
    setWriteError("");
    try {
      await revokeInvite(invite.id);
      setInvites((current) => current.filter((item) => item.id !== invite.id));
    } catch (err) {
      setWriteError(writeErrorMessage(err));
    } finally {
      setActionBusy("");
    }
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

  const adminCount = members.filter((member) => member.role === "admin").length;
  const transferCandidates = removalMember
    ? members.filter((member) => member.id !== removalMember.id)
    : [];
  const transferTarget = transferCandidates.find(
    (member) => member.id === transferTargetId
  );
  const removalBusy = removalMember
    ? actionBusy === `member:${removalMember.id}`
    : false;

  return (
    <div>
      <Dialog
        open={removalMember !== null}
        onOpenChange={(open) => {
          if (!open) closeRemovalDialog();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove {removalMember?.email}</DialogTitle>
            <DialogDescription>
              Their workspace access will be revoked. Sheldon checks their owned work before
              anything is deleted or reassigned.
            </DialogDescription>
          </DialogHeader>

          {removalLoading && (
            <div role="status" aria-live="polite" className="meta">
              Checking owned work...
            </div>
          )}

          {removalError && (
            <div
              role="alert"
              className="card"
              style={{ padding: "10px 12px", color: "var(--yellow)" }}
            >
              {removalError}
            </div>
          )}

          {removalImpact && (
            <div className="grid gap-4">
              <div className="card" style={{ padding: "12px 14px" }}>
                <div className="font-semibold">Removal impact</div>
                {removalImpact.total_assets === 0 ? (
                  <p className="meta" style={{ marginTop: 6 }}>
                    This member has no transferable workspace assets.
                  </p>
                ) : (
                  <ul
                    className="meta"
                    style={{ marginTop: 8, paddingLeft: 18, listStyle: "disc" }}
                  >
                    {removalImpact.assets.automations > 0 && (
                      <li>
                        {removalImpact.assets.automations} automation
                        {removalImpact.assets.automations === 1 ? "" : "s"}
                      </li>
                    )}
                    {removalImpact.assets.private_threads > 0 && (
                      <li>
                        {removalImpact.assets.private_threads} private conversation
                        {removalImpact.assets.private_threads === 1 ? "" : "s"}
                      </li>
                    )}
                    {removalImpact.assets.shared_threads > 0 && (
                      <li>
                        {removalImpact.assets.shared_threads} shared conversation
                        {removalImpact.assets.shared_threads === 1 ? "" : "s"}
                      </li>
                    )}
                    {removalImpact.assets.workflow_runs > 0 && (
                      <li>
                        {removalImpact.assets.workflow_runs} workflow run
                        {removalImpact.assets.workflow_runs === 1 ? "" : "s"}
                      </li>
                    )}
                  </ul>
                )}
                {removalImpact.preserved.saved_artifacts > 0 && (
                  <p className="meta" style={{ marginTop: 8 }}>
                    {removalImpact.preserved.saved_artifacts} saved artifact
                    {removalImpact.preserved.saved_artifacts === 1 ? " keeps" : "s keep"}
                    {" "}the original creator label and will not be assigned to someone else.
                  </p>
                )}
              </div>

              {removalImpact.blocked && (
                <div className="card" role="alert" style={{ padding: "12px 14px" }}>
                  <div className="font-semibold">Removal is blocked</div>
                  <p className="meta" style={{ marginTop: 6 }}>
                    These private or identity-bound records cannot be reassigned safely:
                  </p>
                  <ul className="meta" style={{ marginTop: 8, paddingLeft: 18, listStyle: "disc" }}>
                    {removalImpact.blockers.owned_uploads > 0 && (
                      <li>{removalImpact.blockers.owned_uploads} owned upload{removalImpact.blockers.owned_uploads === 1 ? "" : "s"}</li>
                    )}
                    {removalImpact.blockers.document_access_grants > 0 && (
                      <li>{removalImpact.blockers.document_access_grants} document access grant{removalImpact.blockers.document_access_grants === 1 ? "" : "s"}</li>
                    )}
                    {removalImpact.blockers.private_memories > 0 && (
                      <li>{removalImpact.blockers.private_memories} private memory record{removalImpact.blockers.private_memories === 1 ? "" : "s"}</li>
                    )}
                    {removalImpact.blockers.ask_exchanges > 0 && (
                      <li>{removalImpact.blockers.ask_exchanges} Ask request record{removalImpact.blockers.ask_exchanges === 1 ? "" : "s"}</li>
                    )}
                    {removalImpact.blockers.pending_connector_actions > 0 && (
                      <li>{removalImpact.blockers.pending_connector_actions} pending connector action{removalImpact.blockers.pending_connector_actions === 1 ? "" : "s"}</li>
                    )}
                  </ul>
                  <p className="meta" style={{ marginTop: 8 }}>
                    No ownership or access will change. Resolve these records before trying again.
                  </p>
                </div>
              )}

              {!removalImpact.blocked && removalImpact.requires_transfer && (
                <div className="grid gap-2">
                  <div className="text-caption font-semibold">Transfer ownership to</div>
                  <Select
                    aria-label={`Transfer assets owned by ${removalImpact.member_email} to`}
                    value={transferTargetId || "unselected"}
                    onValueChange={(value) => {
                      setTransferTargetId(value === "unselected" ? "" : value);
                      setRemovalError("");
                    }}
                    disabled={removalBusy || transferCandidates.length === 0}
                    options={[
                      { value: "unselected", label: "Choose a member..." },
                      ...transferCandidates.map((member) => ({
                        value: member.id,
                        label: `${brandText(member.display_name)} (${member.email})`,
                      })),
                    ]}
                  />
                  {transferCandidates.length === 0 && (
                    <p className="error-text" role="alert">
                      No eligible teammate remains. Add another member before removing this one.
                    </p>
                  )}
                  {transferTarget && (
                    <p className="meta" role="status">
                      {brandText(transferTarget.display_name)} will receive ownership. Private
                      conversations will become visible to them. Automations will stay paused and
                      every external trigger link will be revoked.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          <DialogFooter>
            <button
              type="button"
              className="btn"
              onClick={closeRemovalDialog}
              disabled={removalBusy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void confirmRemoveMember()}
              disabled={
                removalBusy ||
                removalLoading ||
                !removalImpact ||
                removalImpact.blocked ||
                (removalImpact.requires_transfer && !transferTargetId)
              }
            >
              <UserMinus className="size-3.5" />
              {removalBusy
                ? "Removing..."
                : removalImpact?.requires_transfer
                  ? "Transfer and remove"
                  : "Remove member"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
            <button type="button" className="btn btn-primary" onClick={() => void refresh(isAdmin)}>Retry</button>
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
              <th style={{ width: 120 }}>Actions</th>
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
                    disabled={!isAdmin || (m.role === "admin" && adminCount === 1)}
                    title={
                      m.role === "admin" && adminCount === 1
                        ? "Add or promote another admin before changing this role."
                        : undefined
                    }
                    options={ROLES.map((value) => ({ value, label: value }))}
                  />
                  {m.role === "admin" && adminCount === 1 && (
                    <div className="meta" style={{ marginTop: 4 }}>Only admin</div>
                  )}
                </td>
                <td>
                  <Select
                    aria-label={`Department for ${brandText(m.display_name)}`}
                    style={{ height: 30 }}
                    value={m.department_id ?? "unassigned"}
                    onValueChange={(value) => changeMember(m, { department_id: value === "unassigned" ? null : value })}
                    disabled={!isAdmin}
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
                      disabled={!isAdmin}
                      options={TIERS.map((value) => ({ value, label: TIER_LABEL[value] }))}
                    />
                  )}
                </td>
                <td>
                  {isAdmin && (
                    <button
                      type="button"
                      className="btn"
                      style={{ fontSize: 11, padding: "4px 10px" }}
                      onClick={() => void handleRemoveMember(m)}
                      disabled={
                        !!actionBusy ||
                        m.id === currentUserId ||
                        (m.role === "admin" && adminCount === 1)
                      }
                      title={m.id === currentUserId ? "Use Settings to delete your own account." : undefined}
                    >
                      <UserMinus className="size-3.5" /> Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {members.length === 0 && (
              <tr>
                <td colSpan={5} style={{ textAlign: "center", color: "var(--text-muted)", padding: "32px 16px" }}>
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
          {isAdmin ? <form onSubmit={handleAddDept} style={{ display: "flex", gap: 8, marginBottom: 18, maxWidth: 420 }}>
            <label className="sr-only" htmlFor="new-department-name">New department name</label>
            <input id="new-department-name" name="department" className="search-input" placeholder="New department name…" required value={deptName} onChange={(e) => setDeptName(e.target.value)} disabled={addingDepartment} />
            <button type="submit" className="btn btn-primary" style={{ whiteSpace: "nowrap" }} disabled={addingDepartment || !deptName.trim()}>
              <Plus className="size-3.5" /> {addingDepartment ? "Adding..." : "Add"}
            </button>
          </form> : <p className="meta" style={{ marginBottom: 18 }}>Only workspace admins can add departments.</p>}
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
                {isAdmin && (
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      type="button"
                      className="btn"
                      aria-label={`Rename ${brandText(d.name)}`}
                      onClick={() => void handleRenameDepartment(d)}
                      disabled={!!actionBusy}
                    >
                      <Pencil className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      className="btn"
                      aria-label={`Delete ${brandText(d.name)}`}
                      onClick={() => void handleRemoveDepartment(d)}
                      disabled={!!actionBusy}
                      title={d.members ? "Reassign members before deleting this department." : undefined}
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* INVITES */}
      {!loading && !loadError && tab === "invites" && (
        <div role="tabpanel" id="team-panel-invites" aria-labelledby="team-tab-invites">
          {!isAdmin ? (
            <div className="card async-state">Only workspace admins can create or view invitations.</div>
          ) : <><form
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
              {inviting ? "Creating…" : "Create invite link"}
            </button>
          </form>

          <p className="meta" style={{ marginBottom: 12 }}>
            Sheldon does not send an email. Copy and share the invite link with the teammate. When they sign in with Google using that email,
            they join this workspace with the role and department you set.
          </p>

          <div className="table-scroll" tabIndex={0} role="region" aria-label="Pending team invitations">
            <table className="data-table">
            <thead>
              <tr>
                <th>Email</th>
                <th style={{ width: 110 }}>Role</th>
                <th style={{ width: 120 }}>Data access</th>
                <th style={{ width: 240 }}>Actions</th>
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
                    <div style={{ display: "flex", gap: 6 }}>
                    <button
                      type="button"
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
                    <button
                      type="button"
                      className="btn"
                      style={{ fontSize: 11, padding: "4px 10px" }}
                      onClick={() => void handleRevokeInvite(i)}
                      disabled={!!actionBusy}
                    >
                      <Trash2 className="size-3.5" /> Revoke
                    </button>
                    </div>
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
          </div></>}
        </div>
      )}
    </div>
  );
}
