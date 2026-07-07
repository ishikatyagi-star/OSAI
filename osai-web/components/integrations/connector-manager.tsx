"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  FileText,
  Loader2,
  Plug,
  PlugZap,
  Plus,
  RefreshCw,
  ShieldAlert,
  Trash2,
  XCircle,
} from "lucide-react";
import {
  getConnectorDocuments,
  getHealthcheck,
  getTierRules,
  putTierRules,
  type ConnectorDocument,
  type TierRule,
} from "@/lib/api";
import { CONNECTOR_META } from "@/lib/connector-meta";
import type { Integration, SyncRun } from "@/lib/types";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

type Health = { healthy: boolean; message: string } | null;

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const RUN_TONE: Record<SyncRun["status"], string> = {
  succeeded: "text-success",
  running: "text-info",
  failed: "text-destructive",
};

export function ConnectorManager({
  integration,
  open,
  onOpenChange,
  recentRuns,
  syncing,
  onSync,
  onToggleConnection,
}: {
  integration: Integration | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  recentRuns: SyncRun[];
  syncing: boolean;
  onSync: (key: string) => void;
  onToggleConnection: (key: string, connect: boolean) => void;
}) {
  const [health, setHealth] = useState<Health>(null);
  const [checking, setChecking] = useState(false);

  // Recently synced files for this connector.
  const [docs, setDocs] = useState<ConnectorDocument[]>([]);

  // Per-info data-tier rules (e.g. a specific Drive folder = Red).
  const [rules, setRules] = useState<TierRule[]>([]);
  const [newPattern, setNewPattern] = useState("");
  const [newTier, setNewTier] = useState<TierRule["tier"]>("red");
  const [rulesSaving, setRulesSaving] = useState(false);
  const [rulesSaved, setRulesSaved] = useState(false);

  const meta =
    integration && CONNECTOR_META[integration.key]
      ? CONNECTOR_META[integration.key]
      : null;
  const ConnectorIcon = meta?.icon ?? Plug;
  const connected = integration?.auth_state === "connected";

  async function runHealthcheck(key: string) {
    setChecking(true);
    try {
      setHealth(await getHealthcheck(key));
    } finally {
      setChecking(false);
    }
  }

  // Auto health-check + load tier rules whenever a connected connector opens.
  useEffect(() => {
    if (open && integration && integration.auth_state === "connected") {
      runHealthcheck(integration.key);
      getTierRules(integration.key).then((r) => setRules(r.rules));
      getConnectorDocuments(integration.key).then(setDocs);
    } else {
      setHealth(null);
      setRules([]);
      setDocs([]);
    }
    setNewPattern("");
    setRulesSaved(false);
  }, [open, integration]);

  function addRule(pattern: string, tier: TierRule["tier"]) {
    const p = pattern.trim();
    if (!p) return;
    setRules((prev) => [...prev.filter((r) => r.pattern !== p), { pattern: p, tier }]);
    setNewPattern("");
    setRulesSaved(false);
  }

  function removeRule(pattern: string) {
    setRules((prev) => prev.filter((r) => r.pattern !== pattern));
    setRulesSaved(false);
  }

  // Files are classified by an exact-title rule; everything unruled stays Normal.
  const docTitles = new Set(docs.map((d) => d.title));
  function tierForFile(title: string): TierRule["tier"] {
    return rules.find((r) => r.pattern === title)?.tier ?? "normal";
  }
  function setFileTier(title: string, tier: TierRule["tier"]) {
    setRules((prev) => {
      const without = prev.filter((r) => r.pattern !== title);
      return tier === "normal" ? without : [...without, { pattern: title, tier }];
    });
    setRulesSaved(false);
  }
  // Keyword/folder rules = patterns that aren't an exact synced-file title.
  const keywordRules = rules.filter((r) => !docTitles.has(r.pattern));
  // Preview/autocomplete for the keyword box. On focus (empty box) we preview
  // the available synced files so the user can pick one; as they type we filter.
  const [patternFocused, setPatternFocused] = useState(false);
  const query = newPattern.trim().toLowerCase();
  const suggestions = !patternFocused
    ? []
    : (query
        ? docs.filter((d) => d.title.toLowerCase().includes(query))
        : docs
      ).slice(0, 8);

  async function saveRules() {
    if (!integration) return;
    setRulesSaving(true);
    try {
      const res = await putTierRules(integration.key, rules);
      setRules(res.rules);
      setRulesSaved(true);
    } catch {
      // Backend unreachable — keep local state; surfaced by absence of saved tick.
    } finally {
      setRulesSaving(false);
      setTimeout(() => setRulesSaved(false), 3000);
    }
  }

  if (!integration) return null;

  const TIER_DOT: Record<TierRule["tier"], string> = {
    normal: "var(--green)",
    amber: "var(--yellow, var(--orange))",
    red: "var(--red)",
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div
              className="flex size-10 items-center justify-center rounded-lg border border-border bg-secondary text-muted-foreground"
              aria-hidden
            >
              <ConnectorIcon className="size-5" strokeWidth={1.8} />
            </div>
            <div>
              <DialogTitle>{meta?.label ?? integration.display_name}</DialogTitle>
              <DialogDescription>
                {connected
                  ? integration.account_email
                    ? `Connected as ${integration.account_email}`
                    : "Connected"
                  : "Not connected"}
                {integration.last_sync &&
                  ` · last synced ${relativeTime(integration.last_sync)}`}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {connected && integration.previous_account_email && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-2 text-[11px] text-foreground/80">
            Reconnected with a different account
            {integration.last_reconnected_at
              ? ` ${relativeTime(integration.last_reconnected_at)}`
              : ""}
            . Files from <span className="font-medium">{integration.previous_account_email}</span>{" "}
            were removed from the knowledge base; only{" "}
            <span className="font-medium">{integration.account_email ?? "the current account"}</span>{" "}
            is searchable now.
          </div>
        )}

        {/* Scopes / capabilities */}
        <section>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Capabilities &amp; scopes
          </p>
          <div className="flex flex-wrap gap-1.5">
            {integration.capabilities?.map((c) => (
              <Badge key={c} variant="secondary">
                {c}
              </Badge>
            ))}
            {integration.scopes?.map((s) => (
              <Badge key={s} variant="muted">
                {s}
              </Badge>
            ))}
            {!integration.capabilities?.length && !integration.scopes?.length && (
              <span className="text-xs text-muted-foreground">
                No scopes granted yet.
              </span>
            )}
          </div>
        </section>

        {/* Health */}
        {connected && (
          <section className="rounded-lg border border-border bg-background/40 p-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Activity className="size-3.5" /> Connection health
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-7"
                disabled={checking}
                onClick={() => runHealthcheck(integration.key)}
              >
                {checking ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="size-3.5" />
                )}
                Re-check
              </Button>
            </div>
            <div className="mt-2 flex items-center gap-2 text-sm">
              {checking ? (
                <span className="text-muted-foreground">Checking…</span>
              ) : health ? (
                <>
                  {health.healthy ? (
                    <CheckCircle2 className="size-4 text-success" />
                  ) : (
                    <XCircle className="size-4 text-destructive" />
                  )}
                  <span
                    className={health.healthy ? "text-success" : "text-destructive"}
                  >
                    {health.message}
                  </span>
                </>
              ) : (
                <span className="text-muted-foreground">Not checked yet.</span>
              )}
            </div>
            {integration.sync_error && (
              <p className="mt-2 inline-flex items-start gap-1.5 text-xs text-destructive">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.8} />
                <span>{integration.sync_error}</span>
              </p>
            )}
          </section>
        )}

        {/* Recent syncs */}
        {connected && (
          <section>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Recent syncs
            </p>
            {recentRuns.length === 0 ? (
              <p className="text-xs text-muted-foreground">No sync runs yet.</p>
            ) : (
              <ul className="space-y-1">
                {recentRuns.slice(0, 4).map((r) => (
                  <li
                    key={r.id}
                    className="flex items-center justify-between rounded-md border border-border bg-background/40 px-2.5 py-1.5 text-xs"
                  >
                    <span className={`font-medium capitalize ${RUN_TONE[r.status]}`}>
                      {r.status}
                    </span>
                    <span className="text-muted-foreground">
                      {r.documents_indexed}/{r.documents_seen} docs ·{" "}
                      {relativeTime(r.started_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {/* Classify synced files — pick a tier per file (default Normal/green) */}
        {connected && (
          <section className="rounded-lg border border-border bg-background/40 p-3">
            <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <FileText className="size-3.5" /> Files &amp; sensitivity ({docs.length})
            </p>
            <p className="mb-2.5 text-[11px] text-muted-foreground">
              Choose a tier for any file. Everything stays{" "}
              <span style={{ color: "var(--green)" }}>Normal</span> unless you change it.
            </p>

            {docs.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Nothing indexed yet — click “Sync now” to pull in this source.
              </p>
            ) : (
              <ul className="max-h-52 space-y-1 overflow-y-auto">
                {docs.map((d) => {
                  const tier = tierForFile(d.title);
                  return (
                    <li
                      key={d.id}
                      className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs"
                    >
                      <span
                        className="inline-block size-2 shrink-0 rounded-full"
                        style={{ background: TIER_DOT[tier] }}
                      />
                      <span className="min-w-0 flex-1 truncate text-foreground/90">
                        {d.url ? (
                          <a href={d.url} target="_blank" rel="noreferrer" className="hover:underline">
                            {d.title}
                          </a>
                        ) : (
                          d.title
                        )}
                      </span>
                      <select
                        className="select"
                        style={{ height: 26, fontSize: 11 }}
                        value={tier}
                        onChange={(e) => setFileTier(d.title, e.target.value as TierRule["tier"])}
                      >
                        <option value="normal">Normal</option>
                        <option value="amber">Amber</option>
                        <option value="red">Red</option>
                      </select>
                    </li>
                  );
                })}
              </ul>
            )}

            {/* Folder / keyword rule with autocomplete against file names */}
            <div className="mt-3 border-t border-border pt-3">
              <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <ShieldAlert className="size-3.5" /> Rule by folder or keyword
              </p>
              <div className="relative flex items-center gap-1.5">
                <div className="relative flex-1">
                  <Input
                    value={newPattern}
                    onChange={(e) => setNewPattern(e.target.value)}
                    onFocus={() => setPatternFocused(true)}
                    // Delay blur so a click on a suggestion registers first.
                    onBlur={() => setTimeout(() => setPatternFocused(false), 150)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addRule(newPattern, newTier);
                      }
                    }}
                    placeholder="Type or pick a folder or file name…"
                    className="h-8"
                  />
                  {suggestions.length > 0 && (
                    <ul className="absolute z-10 mt-1 max-h-40 w-full overflow-y-auto rounded-md border border-border bg-card shadow-lg">
                      {!query && (
                        <li className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                          Synced files
                        </li>
                      )}
                      {suggestions.map((s) => (
                        <li key={s.id}>
                          <button
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => addRule(s.title, newTier)}
                            className="block w-full truncate px-2.5 py-1.5 text-left text-xs hover:bg-accent"
                          >
                            {s.title}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {patternFocused && docs.length === 0 && (
                    <div className="absolute z-10 mt-1 w-full rounded-md border border-border bg-card px-2.5 py-2 text-[11px] text-muted-foreground shadow-lg">
                      No synced files yet — run “Sync now” to pull files in, then
                      they’ll appear here to pick from. You can still type a
                      folder or keyword rule.
                    </div>
                  )}
                </div>
                <select
                  className="select"
                  style={{ height: 32, fontSize: 12 }}
                  value={newTier}
                  onChange={(e) => setNewTier(e.target.value as TierRule["tier"])}
                >
                  <option value="normal">Normal</option>
                  <option value="amber">Amber</option>
                  <option value="red">Red</option>
                </select>
                <Button variant="ghost" size="sm" className="h-8" onClick={() => addRule(newPattern, newTier)}>
                  <Plus className="size-3.5" /> Add
                </Button>
              </div>

              {keywordRules.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {keywordRules.map((r) => (
                    <li
                      key={r.pattern}
                      className="flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs"
                    >
                      <span className="inline-block size-2 shrink-0 rounded-full" style={{ background: TIER_DOT[r.tier] }} />
                      <span className="min-w-0 flex-1 truncate font-mono text-foreground/90">{r.pattern}</span>
                      <Badge variant="muted" className="capitalize">{r.tier}</Badge>
                      <button
                        type="button"
                        onClick={() => removeRule(r.pattern)}
                        className="text-muted-foreground hover:text-destructive"
                        aria-label={`Remove rule ${r.pattern}`}
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="mt-3 flex items-center gap-2">
              <Button size="sm" className="h-7" disabled={rulesSaving} onClick={saveRules}>
                {rulesSaving ? <Loader2 className="size-3.5 animate-spin" /> : null}
                Save tiers
              </Button>
              {rulesSaved && (
                <span className="inline-flex items-center gap-1.5 text-xs text-success">
                  <Check className="size-3.5" strokeWidth={2} />
                  Saved — applies on next sync
                </span>
              )}
            </div>
          </section>
        )}

        <Separator />

        {/* Actions */}
        <div className="flex items-center justify-between gap-2">
          {connected ? (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => onToggleConnection(integration.key, false)}
            >
              <Plug className="size-3.5" /> Disconnect
            </Button>
          ) : (
            <span className="text-xs text-muted-foreground">
              Authorize to start indexing this source.
            </span>
          )}

          {connected ? (
            <Button
              size="sm"
              disabled={syncing}
              onClick={() => onSync(integration.key)}
            >
              {syncing ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" /> Syncing…
                </>
              ) : (
                <>
                  <RefreshCw className="size-3.5" /> Sync now
                </>
              )}
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={() => onToggleConnection(integration.key, true)}
            >
              <PlugZap className="size-3.5" /> Connect
            </Button>
          )}
        </div>
        {!connected && (
          <p className="-mt-2 text-[11px] text-muted-foreground">
            Connect redirects you to {meta?.label ?? "the provider"} to authorize
            access. OSAI only requests read-only access to index and search your
            content — it never modifies it.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
