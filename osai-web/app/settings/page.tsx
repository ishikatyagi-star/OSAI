"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FlaskConical, Route, ChevronRight, Trash2, type LucideIcon } from "lucide-react";
import { clearSession, deleteAccount, resetWorkspaceContent, mintSlackAskToken, revokeSlackAskToken } from "@/lib/api";
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
      "Quality and regression tracking for Sheldon's answers and routing. Moved out of the main nav to keep things simple.",
  },
];

export default function SettingsPage() {
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [resetMsg, setResetMsg] = useState("");
  const [slackToken, setSlackToken] = useState<{ token: string; path: string } | null>(null);
  const [slackBusy, setSlackBusy] = useState(false);

  async function handleMintSlack() {
    setSlackBusy(true);
    try {
      const res = await mintSlackAskToken();
      setSlackToken({ token: res.token, path: res.request_url_path });
    } finally {
      setSlackBusy(false);
    }
  }

  async function handleRevokeSlack() {
    setSlackBusy(true);
    try {
      await revokeSlackAskToken();
      setSlackToken(null);
    } finally {
      setSlackBusy(false);
    }
  }

  async function handleReset() {
    const orgId = localStorage.getItem("osai_org_id");
    if (!orgId) return;
    setResetting(true);
    setResetMsg("");
    try {
      const res = await resetWorkspaceContent(orgId);
      const total = Object.values(res.deleted).reduce((a, b) => a + b, 0);
      setResetMsg(`Cleared ${total} records. Re-sync your connectors to pull real data.`);
      setDialogOpen(false);
    } catch {
      setResetMsg("Couldn't reset - please try again.");
    } finally {
      setResetting(false);
    }
  }

  async function handleDeleteAccount() {
    setDeleting(true);
    try {
      await deleteAccount();
    } catch {
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

      {/* Danger Zone separator */}
      <div style={{ position: "relative", margin: "36px 0 18px", display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ flex: 1, height: 1, background: "color-mix(in srgb, var(--red) 40%, var(--border))" }} />
        <span style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--red)", whiteSpace: "nowrap" }}>
          Danger Zone
        </span>
        <div style={{ flex: 1, height: 1, background: "color-mix(in srgb, var(--red) 40%, var(--border))" }} />
      </div>

      {/* Slack /ask slash command */}
      <div className="card" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Ask from Slack</h2>
        <p className="meta" style={{ margin: "4px 0 12px", lineHeight: 1.5 }}>
          Create a token, then add a Slack slash command (e.g. /ask) whose Request URL
          points at your OSAI API: <code>&lt;api-base&gt;/slack/ask/&lt;token&gt;</code>.
          Teammates get cited answers without leaving Slack.
        </p>
        {slackToken && (
          <div className="card" style={{ padding: "8px 12px", marginBottom: 10, fontSize: 12 }}>
            <p style={{ margin: 0, fontWeight: 600 }}>Request URL path (copy now — shown once):</p>
            <code style={{ wordBreak: "break-all" }}>{slackToken.path}</code>
          </div>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-primary" disabled={slackBusy} onClick={handleMintSlack}>
            {slackToken ? "Rotate token" : "Create token"}
          </button>
          <button className="btn" disabled={slackBusy} onClick={handleRevokeSlack}>
            Revoke
          </button>
        </div>
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
            <button className="btn btn-danger" onClick={() => { setResetMsg(""); setDialogOpen(true); }}>
              Clear workspace data
            </button>
          </div>
        </div>
      </div>

      <div
        className="card"
        style={{ marginTop: 12, borderColor: "color-mix(in srgb, var(--red) 35%, var(--border))" }}
      >
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
            <button className="btn btn-danger" onClick={() => setDeleteDialogOpen(true)}>
              Delete account
            </button>
          </div>
        </div>
      </div>

      {/* Confirmation modal */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clear workspace data</DialogTitle>
            <DialogDescription>
              Are you sure? This will permanently delete all indexed documents, decisions,
              workflows and sample data. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button className="btn" onClick={() => setDialogOpen(false)} disabled={resetting}>
              Cancel
            </button>
            <button className="btn btn-danger" onClick={handleReset} disabled={resetting}>
              {resetting ? "Clearing\u2026" : "Yes, clear data"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete account</DialogTitle>
            <DialogDescription>
              Permanently delete your account? This cannot be undone, and you will be signed out.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button className="btn" onClick={() => setDeleteDialogOpen(false)} disabled={deleting}>
              Cancel
            </button>
            <button className="btn btn-danger" onClick={handleDeleteAccount} disabled={deleting}>
              {deleting ? "Deleting…" : "Yes, delete account"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
