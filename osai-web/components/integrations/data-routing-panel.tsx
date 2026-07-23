"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  RotateCw,
  Save,
  ShieldCheck,
} from "lucide-react";
import { ApiError, getDataRouting, patchDataRouting } from "@/lib/api";
import { CONNECTOR_META } from "@/lib/connector-meta";
import {
  DATA_ROUTING_TIERS,
  DENY_ALL_DATA_ROUTING,
  DataRoutingValidationError,
  dataRoutingEquals,
} from "@/lib/data-routing";
import { DEMO_DATA_ROUTING } from "@/lib/demo-data";
import type { DataRouting, DataRoutingTier } from "@/lib/types";
import { Button } from "@/components/ui/button";

type DataRoutingPanelProps = {
  demo: boolean;
  isAdmin: boolean;
  roleResolved: boolean;
  roleError: boolean;
  onRefreshRole: () => Promise<boolean | null>;
};

type Feedback = { tone: "success" | "error"; message: string } | null;

const ROUTING_DESTINATIONS = [
  "notion",
  "slack",
  "freshdesk",
  "google_drive",
  "composio_search",
] as const;

const ROUTING_DESTINATION_LABELS: Record<string, string> = {
  composio_search: "Web search (Composio)",
};

const TIER_META: Record<
  DataRoutingTier,
  { title: string; description: string; color: string; badge: string }
> = {
  normal: {
    title: "Normal",
    description: "Standard company data.",
    color: "var(--green)",
    badge: "badge-green",
  },
  amber: {
    title: "Amber",
    description: "Sensitive business data.",
    color: "var(--yellow)",
    badge: "badge-amber",
  },
  red: {
    title: "Red",
    description: "Restricted or confidential data.",
    color: "var(--red)",
    badge: "badge-red",
  },
};

function copyRouting(routing: DataRouting): DataRouting {
  return {
    normal: {
      llm_allowed: routing.normal.llm_allowed,
      allowed_connectors: [...routing.normal.allowed_connectors],
    },
    amber: {
      llm_allowed: routing.amber.llm_allowed,
      allowed_connectors: [...routing.amber.allowed_connectors],
    },
    red: {
      llm_allowed: routing.red.llm_allowed,
      allowed_connectors: [...routing.red.allowed_connectors],
    },
  };
}

function sameRouting(left: DataRouting | null, right: DataRouting | null) {
  return left !== null && right !== null && dataRoutingEquals(left, right);
}

function destinationLabel(key: string) {
  return ROUTING_DESTINATION_LABELS[key] ?? CONNECTOR_META[key]?.label ?? key.replaceAll("_", " ");
}

export function DataRoutingPanel({
  demo,
  isAdmin,
  roleResolved,
  roleError,
  onRefreshRole,
}: DataRoutingPanelProps) {
  const [confirmed, setConfirmed] = useState<DataRouting | null>(null);
  const [draft, setDraft] = useState<DataRouting | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadErrorKind, setLoadErrorKind] = useState<"invalid" | "unavailable" | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [saving, setSaving] = useState(false);
  const [outcomeUnknown, setOutcomeUnknown] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);

  useEffect(() => {
    let active = true;
    setLoadState("loading");
    setConfirmed(null);
    setDraft(null);
    setFeedback(null);
    setLoadErrorKind(null);
    setOutcomeUnknown(false);

    async function load() {
      try {
        const policy = demo ? copyRouting(DEMO_DATA_ROUTING) : await getDataRouting();
        if (!active) return;
        setConfirmed(copyRouting(policy));
        setDraft(copyRouting(policy));
        setLoadErrorKind(null);
        setLoadState("ready");
      } catch (error) {
        if (!active) return;
        // Do not substitute defaults here. Policy availability and validity are
        // part of the authorization decision, so an error has no editable state.
        setLoadErrorKind(
          error instanceof DataRoutingValidationError ? "invalid" : "unavailable"
        );
        setLoadState("error");
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [demo, reloadToken]);

  const canEdit = roleResolved && isAdmin && !demo && !outcomeUnknown;
  const visibleRouting = canEdit ? draft : confirmed;
  const dirty = canEdit && !sameRouting(draft, confirmed);

  const destinations = useMemo(() => {
    const keys = new Set<string>(ROUTING_DESTINATIONS);
    for (const routing of [confirmed, draft]) {
      if (!routing) continue;
      for (const tier of DATA_ROUTING_TIERS) {
        routing[tier].allowed_connectors.forEach((key) => keys.add(key));
      }
    }
    return [...keys];
  }, [confirmed, draft]);

  function updateTier(
    tier: DataRoutingTier,
    update: (current: DataRouting[DataRoutingTier]) => DataRouting[DataRoutingTier]
  ) {
    if (!canEdit || !draft) return;
    setDraft({ ...draft, [tier]: update(draft[tier]) });
    setFeedback(null);
  }

  function toggleDestination(tier: DataRoutingTier, connector: string) {
    updateTier(tier, (current) => ({
      ...current,
      allowed_connectors: current.allowed_connectors.includes(connector)
        ? current.allowed_connectors.filter((item) => item !== connector)
        : [...current.allowed_connectors, connector],
    }));
  }

  async function reconcileFailedMutation(
    attempted: DataRouting,
    previous: DataRouting | null,
    error: unknown,
    recovery: boolean
  ) {
    const authorizationFailure =
      error instanceof ApiError && (error.status === 401 || error.status === 403);
    try {
      const current = await getDataRouting();
      setConfirmed(copyRouting(current));
      setLoadErrorKind(null);
      setLoadState("ready");
      setOutcomeUnknown(false);

      if (dataRoutingEquals(current, attempted)) {
        setDraft(copyRouting(current));
        setFeedback({
          tone: "success",
          message: recovery
            ? "Deny-all routing policy is active and confirmed by the server."
            : "Routing policy is active and confirmed after reloading the server state.",
        });
      } else if (previous && dataRoutingEquals(current, previous)) {
        setDraft(copyRouting(attempted));
        setFeedback({
          tone: "error",
          message:
            "The server still reports the previous policy. Your unsaved changes are retained and can be retried.",
        });
      } else {
        setDraft(copyRouting(current));
        setFeedback({
          tone: "error",
          message:
            "The server reports a different current policy. That server-confirmed policy is shown; review it before editing again.",
        });
      }
    } catch {
      // A failed write can have committed before its response was lost. If the
      // follow-up read also fails, no browser claim about the active policy is safe.
      setOutcomeUnknown(true);
      setLoadState(previous ? "ready" : "error");
      setFeedback({
        tone: "error",
        message:
          "Save outcome is unknown because the server policy could not be reloaded. Editing is locked until you reload the policy.",
      });
    } finally {
      if (authorizationFailure) await onRefreshRole();
    }
  }

  async function save() {
    if (!canEdit || !draft || !confirmed || saving || !dirty) return;
    const attempted = copyRouting(draft);
    const previous = copyRouting(confirmed);
    setSaving(true);
    setFeedback(null);
    try {
      const updated = await patchDataRouting(attempted, previous);
      setConfirmed(copyRouting(updated));
      setDraft(copyRouting(updated));
      setOutcomeUnknown(false);
      setFeedback({
        tone: "success",
        message: "Routing policy saved and confirmed by the server.",
      });
    } catch (error) {
      await reconcileFailedMutation(attempted, previous, error, false);
    } finally {
      setSaving(false);
    }
  }

  async function recoverWithDenyAll() {
    if (!roleResolved || !isAdmin || demo || saving || loadErrorKind !== "invalid") return;
    if (
      !window.confirm(
        "Reset data routing to deny all? This blocks every tier from cloud LLM processing and every external connector destination until an admin explicitly enables them."
      )
    ) {
      return;
    }

    const attempted = copyRouting(DENY_ALL_DATA_ROUTING);
    setSaving(true);
    setFeedback(null);
    try {
      const updated = await patchDataRouting(attempted, null);
      setConfirmed(copyRouting(updated));
      setDraft(copyRouting(updated));
      setLoadErrorKind(null);
      setLoadState("ready");
      setOutcomeUnknown(false);
      setFeedback({
        tone: "success",
        message: "Deny-all routing policy saved and confirmed by the server.",
      });
    } catch (error) {
      await reconcileFailedMutation(attempted, null, error, true);
    } finally {
      setSaving(false);
    }
  }

  if (loadState === "loading") {
    return (
      <div className="card async-state" role="status" aria-live="polite">
        Loading data-routing policies...
      </div>
    );
  }

  if (outcomeUnknown && !visibleRouting) {
    return (
      <div className="card async-state" role="alert">
        <div>
          <p className="error-text" style={{ marginBottom: 8, fontWeight: 600 }}>
            Save outcome is unknown.
          </p>
          <p className="meta" style={{ marginBottom: 16 }}>
            The server policy could not be verified after the save attempt. Editing stays locked
            until the policy is reloaded.
          </p>
          <Button type="button" onClick={() => setReloadToken((value) => value + 1)}>
            <RotateCw className="size-3.5" /> Reload policy
          </Button>
        </div>
      </div>
    );
  }

  if (loadState === "error" || !visibleRouting) {
    const invalid = loadErrorKind === "invalid";
    const canRecover = invalid && roleResolved && isAdmin && !demo;
    return (
      <div className="card async-state" role="alert">
        <div>
          <p className="error-text" style={{ marginBottom: 8, fontWeight: 600 }}>
            {invalid
              ? "Stored routing settings are invalid."
              : "Routing settings could not be loaded safely."}
          </p>
          <p className="meta" style={{ marginBottom: 16 }}>
            {invalid
              ? "No policy is shown or editable. An admin can explicitly replace it with a deny-all policy."
              : "No policy is shown because the service is unavailable. No routing change was made."}
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            <Button type="button" onClick={() => setReloadToken((value) => value + 1)}>
              <RotateCw className="size-3.5" /> Retry
            </Button>
            {canRecover && (
              <Button
                type="button"
                variant="destructive"
                disabled={saving}
                onClick={() => void recoverWithDenyAll()}
              >
                <ShieldCheck className="size-3.5" />
                {saving ? "Resetting..." : "Reset to deny-all"}
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <section aria-labelledby="data-routing-heading">
      <div className="card" style={{ marginBottom: 16, padding: "14px 16px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div>
            <h2 id="data-routing-heading" style={{ fontSize: 14, marginBottom: 4 }}>
              Data-routing policy
            </h2>
            <p className="meta" style={{ margin: 0 }}>
              {demo
                ? "Demo preview. Routing settings cannot be changed in the shared workspace."
                : !roleResolved
                  ? "Checking your workspace permissions. Editing controls stay hidden until the check completes."
                  : roleError && !isAdmin
                    ? "Workspace permissions could not be verified. Editing remains disabled until the check succeeds."
                    : roleError
                      ? "Admin access was confirmed earlier, but the permission refresh failed. The server still checks every save."
                  : isAdmin
                    ? "Admins can edit this policy. A change is active only after the server confirms the save."
                    : "View only. Only workspace admins can change data-routing policy."}
            </p>
            {roleError && !demo && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                style={{ marginTop: 10 }}
                onClick={() => void onRefreshRole()}
              >
                <RotateCw className="size-3.5" /> Retry permission check
              </Button>
            )}
          </div>
        </div>
      </div>

      {outcomeUnknown && (
        <div className="card" role="alert" style={{ marginBottom: 16, padding: "14px 16px" }}>
          <p className="error-text" style={{ marginBottom: 6, fontWeight: 600 }}>
            Save outcome is unknown. Editing is locked.
          </p>
          <p className="meta" style={{ marginBottom: 12 }}>
            The policy below is the last browser-confirmed copy and may be stale. Reload the
            server policy before making another change.
          </p>
          <Button type="button" onClick={() => setReloadToken((value) => value + 1)}>
            <RotateCw className="size-3.5" /> Reload policy
          </Button>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {DATA_ROUTING_TIERS.map((tier) => {
          const meta = TIER_META[tier];
          const policy = visibleRouting[tier];
          return (
            <article className="card" key={tier} style={{ padding: 0, overflow: "hidden" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "16px 20px",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <span
                  aria-hidden="true"
                  style={{ width: 4, height: 36, borderRadius: 999, background: meta.color }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <h3 style={{ fontSize: 16, margin: 0 }}>{meta.title}</h3>
                    <span className={`badge ${meta.badge}`}>{tier}</span>
                  </div>
                  <p className="meta" style={{ margin: "3px 0 0" }}>{meta.description}</p>
                </div>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                  gap: 24,
                  padding: "18px 20px 20px",
                }}
              >
                <div>
                  <p
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      marginBottom: 10,
                      fontSize: 12,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.04em",
                      color: "var(--text-secondary)",
                    }}
                  >
                    <Cloud className="size-3.5" aria-hidden="true" /> Cloud LLM processing
                  </p>
                  {canEdit ? (
                    <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13 }}>
                      <input
                        type="checkbox"
                        checked={policy.llm_allowed}
                        onChange={() =>
                          updateTier(tier, (current) => ({
                            ...current,
                            llm_allowed: !current.llm_allowed,
                          }))
                        }
                        aria-label={`Allow cloud LLM processing for ${meta.title} data`}
                      />
                      <span>{policy.llm_allowed ? "Allowed" : "Blocked"}</span>
                    </label>
                  ) : (
                    <p style={{ margin: 0, fontSize: 13 }}>
                      <strong>Cloud LLM:</strong> {policy.llm_allowed ? "Allowed" : "Blocked"}
                    </p>
                  )}
                </div>

                <div>
                  <p
                    style={{
                      marginBottom: 10,
                      fontSize: 12,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.04em",
                      color: "var(--text-secondary)",
                    }}
                  >
                    Allowed connector destinations
                  </p>
                  {canEdit ? (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                      {destinations.map((key) => {
                        const allowed = policy.allowed_connectors.includes(key);
                        return (
                          <label
                            key={key}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 7,
                              minHeight: 36,
                              padding: "7px 11px",
                              border: "1px solid var(--border)",
                              borderRadius: 8,
                              background: allowed ? "var(--bg-elevated)" : "var(--bg-surface)",
                              fontSize: 12,
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={allowed}
                              onChange={() => toggleDestination(tier, key)}
                              aria-label={`Allow ${destinationLabel(key)} destination for ${meta.title} data`}
                            />
                            {destinationLabel(key)}
                          </label>
                        );
                      })}
                    </div>
                  ) : policy.allowed_connectors.length > 0 ? (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                      {policy.allowed_connectors.map((key) => (
                        <span className="badge badge-grey" key={key}>{destinationLabel(key)}</span>
                      ))}
                    </div>
                  ) : (
                    <p className="meta" style={{ margin: 0 }}>No connector destinations allowed.</p>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {canEdit && (
        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 12, marginTop: 18 }}>
          <Button type="button" onClick={() => void save()} disabled={saving || !dirty}>
            <Save className="size-3.5" /> {saving ? "Saving..." : "Save changes"}
          </Button>
          {dirty && !feedback && <span className="meta">Unsaved changes</span>}
        </div>
      )}
      {feedback?.tone === "success" && (
        <span
          className="success-text inline-flex items-center gap-1.5"
          role="status"
          style={{ marginTop: 14 }}
        >
          <CheckCircle2 className="size-3.5" /> {feedback.message}
        </span>
      )}
      {feedback?.tone === "error" && (
        <span
          className="error-text inline-flex items-start gap-1.5"
          role="alert"
          style={{ marginTop: 14 }}
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {feedback.message}
        </span>
      )}
    </section>
  );
}
