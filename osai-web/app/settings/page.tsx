"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Database, FlaskConical, Users, ChevronRight, Trash2, LogOut, type LucideIcon } from "lucide-react";
import { clearSession, deleteAccount, logoutAllSessions, resetWorkspaceContent, mintSlackAskToken, revokeSlackAskToken } from "@/lib/api";
import { isDemo } from "@/lib/demo";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

type SettingsLink = {
  href: string;
  icon: LucideIcon;
  title: string;
  description: string;
};

const LINKS: SettingsLink[] = [
  {
    href: "/team",
    icon: Users,
    title: "Team access",
    description:
      "Manage roles, departments, and Normal / Amber / Red access tiers for your team.",
  },
  {
    href: "/sql",
    icon: Database,
    title: "Data sources",
    description:
      "Connect a read-only database so Sheldon can answer from live data. It writes the SQL, shows it to you, and only runs what you approve.",
  },
  {
    href: "/evals",
    icon: FlaskConical,
    title: "Evals",
    description:
      "Quality and regression tracking for Sheldon's answers and routing. Moved out of the main nav to keep things simple.",
  },
];

export default function SettingsPage() {
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [signOutAllOpen, setSignOutAllOpen] = useState(false);
  const [signingOutAll, setSigningOutAll] = useState(false);
  const [resetMsg, setResetMsg] = useState("");
  const [resetError, setResetError] = useState("");
  const [resetConfirm, setResetConfirm] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [slackToken, setSlackToken] = useState<{ token: string; path: string } | null>(null);
  const [slackBusy, setSlackBusy] = useState(false);
  const [slackError, setSlackError] = useState("");

  async function handleMintSlack() {
    if (isDemo()) {
      setSlackError("Slack token changes are disabled in the shared demo workspace.");
      return;
    }
    setSlackBusy(true);
    setSlackError("");
    try {
      const res = await mintSlackAskToken();
      setSlackToken({ token: res.token, path: res.request_url_path });
    } catch {
      setSlackError("The Slack token could not be created. Please try again.");
    } finally {
      setSlackBusy(false);
    }
  }

  async function handleRevokeSlack() {
    if (isDemo()) {
      setSlackError("Slack token changes are disabled in the shared demo workspace.");
      return;
    }
    setSlackBusy(true);
    setSlackError("");
    try {
      await revokeSlackAskToken();
      setSlackToken(null);
    } catch {
      setSlackError("The Slack token could not be revoked. Please try again.");
    } finally {
      setSlackBusy(false);
    }
  }

  async function handleReset() {
    if (isDemo()) {
      setResetError("Workspace resets are disabled in the shared demo workspace.");
      return;
    }
    const orgId = localStorage.getItem("osai_org_id");
    if (!orgId) return;
    setResetting(true);
    setResetMsg("");
    setResetError("");
    try {
      const res = await resetWorkspaceContent(orgId);
      const total = Object.values(res.deleted).reduce((a, b) => a + b, 0);
      setResetMsg(`Cleared ${total} records. Re-sync your connectors to pull real data.`);
      setDialogOpen(false);
      setResetConfirm("");
    } catch {
      setResetError("The server did not confirm that the reset completed. Refresh before retrying.");
    } finally {
      setResetting(false);
    }
  }

  async function handleDeleteAccount() {
    if (isDemo()) {
      setDeleteError("Account deletion is disabled in the shared demo workspace.");
      return;
    }
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteAccount();
      router.replace("/login");
    } catch {
      setDeleteError("Your account was not deleted. Please try again or contact support.");
    } finally {
      setDeleting(false);
    }
  }

  async function handleSignOutEverywhere() {
    setSigningOutAll(true);
    try {
      await logoutAllSessions();
    } catch {
      // Even if the revoke call fails, drop this device's session so the button
      // never leaves the user believing they're signed out when they aren't.
      clearSession();
    } finally {
      router.replace("/login");
    }
  }

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
                    <h2 style={{ margin: 0 }}>{link.title}</h2>
                    <ChevronRight size={14} style={{ marginLeft: "auto", color: "var(--text-secondary)" }} />
                  </div>
                  <p className="meta" style={{ margin: 0, lineHeight: 1.5 }}>
                    {link.description}
                  </p>
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {/* Slack /ask slash command */}
      <div className="card" style={{ marginTop: 24, marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Ask from Slack</h2>
        <p className="meta" style={{ margin: "4px 0 12px", lineHeight: 1.5 }}>
          Create a token, then add a Slack slash command (e.g. /ask) whose Request URL
          points at your Sheldon API: <code>&lt;api-base&gt;/slack/ask/&lt;token&gt;</code>.
          Teammates get cited answers without leaving Slack.
        </p>
        {slackToken && (
          <div className="card" style={{ padding: "8px 12px", marginBottom: 10, fontSize: 12 }}>
            <p style={{ margin: 0, fontWeight: 600 }}>Request URL path (copy now - shown once):</p>
            <code style={{ wordBreak: "break-all" }}>{slackToken.path}</code>
          </div>
        )}
        {slackError && <p className="error-text" role="alert" style={{ marginBottom: 10 }}>{slackError}</p>}
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn btn-primary" disabled={slackBusy} onClick={handleMintSlack}>
            {slackToken ? "Rotate token" : "Create token"}
          </button>
          <button type="button" className="btn" disabled={slackBusy} onClick={handleRevokeSlack}>
            Revoke
          </button>
        </div>
      </div>

      {/* Danger Zone separator */}
      <div style={{ position: "relative", margin: "36px 0 18px", display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1, height: 1, background: "color-mix(in srgb, var(--red) 40%, var(--border))" }} />
        <span style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--red)", whiteSpace: "nowrap" }}>
          Danger Zone
        </span>
        <div style={{ flex: 1, height: 1, background: "color-mix(in srgb, var(--red) 40%, var(--border))" }} />
      </div>

      {/* Danger zone - clear seeded/ingested content */}
      <div
        className="card"
        style={{ borderColor: "color-mix(in srgb, var(--red) 35%, var(--border))" }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
          <div
            className="connector-icon-badge"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--red)" }}
          >
            <Trash2 size={18} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: 0 }}>Reset workspace data</h2>
            <p className="meta" style={{ margin: "4px 0 12px", lineHeight: 1.5 }}>
              Delete all indexed documents, decisions, workflows and sample data. Your connected
              tools stay connected - just click &quot;Sync now&quot; afterwards to pull your real data back in.
            </p>
            {resetMsg && (
              <p className="success-text" style={{ marginBottom: 10 }}>{resetMsg}</p>
            )}
            {resetError && <p className="error-text" role="alert" style={{ marginBottom: 10 }}>{resetError}</p>}
            <button type="button" className="btn btn-danger" onClick={() => { setResetMsg(""); setResetError(""); setResetConfirm(""); setDialogOpen(true); }}>
              Clear workspace data
            </button>
          </div>
        </div>
      </div>

      <div
        className="card"
        style={{ marginTop: 12, borderColor: "color-mix(in srgb, var(--red) 35%, var(--border))" }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 20 }}>
          <div
            className="connector-icon-badge"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
          >
            <LogOut size={18} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: 0 }}>Sign out everywhere</h2>
            <p className="meta" style={{ margin: "4px 0 12px", lineHeight: 1.5 }}>
              Revoke every active session on all devices. Use this if you&apos;ve lost a device or
              suspect your account is compromised. You&apos;ll need to sign in again here too.
            </p>
            <button className="btn" onClick={() => setSignOutAllOpen(true)}>
              Sign out everywhere
            </button>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
          <div
            className="connector-icon-badge"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--red)" }}
          >
            <Trash2 size={18} strokeWidth={1.75} />
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{ margin: 0 }}>Delete account</h2>
            <p className="meta" style={{ margin: "4px 0 12px", lineHeight: 1.5 }}>
              Permanently delete your account and sign out. This cannot be undone.
            </p>
            <button type="button" className="btn btn-danger" onClick={() => { setDeleteError(""); setDeleteConfirm(""); setDeleteDialogOpen(true); }}>
              Delete account
            </button>
          </div>
        </div>
      </div>

      {/* Confirmation modal */}
      <Dialog open={dialogOpen} onOpenChange={(open) => { if (!resetting) { setDialogOpen(open); if (!open) setResetConfirm(""); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clear workspace data</DialogTitle>
            <DialogDescription>
              Clear the indexed content and workflow data currently supported by the server.
              Account configuration remains. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <label className="text-caption" style={{ display: "grid", gap: 6 }}>
            Type <strong>CLEAR</strong> to confirm
            <input className="search-input" value={resetConfirm} onChange={(event) => setResetConfirm(event.target.value)} autoComplete="off" />
          </label>
          {resetError && <p className="error-text" role="alert">{resetError}</p>}
          <DialogFooter>
            <button type="button" className="btn" onClick={() => setDialogOpen(false)} disabled={resetting}>
              Cancel
            </button>
            <button type="button" className="btn btn-danger" onClick={handleReset} disabled={resetting || resetConfirm !== "CLEAR"}>
              {resetting ? "Clearing\u2026" : "Yes, clear data"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={signOutAllOpen} onOpenChange={setSignOutAllOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sign out everywhere</DialogTitle>
            <DialogDescription>
              This revokes every active session on all devices, including this one. Anyone using
              your account will be signed out and will need to sign in again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button className="btn" onClick={() => setSignOutAllOpen(false)} disabled={signingOutAll}>
              Cancel
            </button>
            <button className="btn btn-danger" onClick={handleSignOutEverywhere} disabled={signingOutAll}>
              {signingOutAll ? "Signing out…" : "Sign out everywhere"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteDialogOpen} onOpenChange={(open) => { if (!deleting) { setDeleteDialogOpen(open); if (!open) setDeleteConfirm(""); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete account</DialogTitle>
            <DialogDescription>
              Permanently delete your account? This cannot be undone, and you will be signed out.
            </DialogDescription>
          </DialogHeader>
          <label className="text-caption" style={{ display: "grid", gap: 6 }}>
            Type <strong>DELETE</strong> to confirm
            <input className="search-input" value={deleteConfirm} onChange={(event) => setDeleteConfirm(event.target.value)} autoComplete="off" />
          </label>
          {deleteError && <p className="error-text" role="alert">{deleteError}</p>}
          <DialogFooter>
            <button type="button" className="btn" onClick={() => setDeleteDialogOpen(false)} disabled={deleting}>
              Cancel
            </button>
            <button type="button" className="btn btn-danger" onClick={handleDeleteAccount} disabled={deleting || deleteConfirm !== "DELETE"}>
              {deleting ? "Deleting…" : "Yes, delete account"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
