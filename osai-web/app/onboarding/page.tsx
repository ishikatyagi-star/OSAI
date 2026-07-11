"use client";

import { useCallback, useMemo, useState } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Loader2,
  SkipForward,
  Sparkles,
} from "lucide-react";
import { composioConnect, login, onboardOrg } from "@/lib/api";
import { CONNECTOR_META, getConnectorIcon } from "@/lib/connector-meta";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const CONNECTOR_FLOW = ["notion", "google_drive", "slack", "freshdesk"] as const;

type ConnectorKey = (typeof CONNECTOR_FLOW)[number];
type Phase = "connect" | "org" | "done";

export default function OnboardingPage() {
  const [phase, setPhase] = useState<Phase>("connect");
  const [stepIndex, setStepIndex] = useState(0);
  const [connected, setConnected] = useState<Set<ConnectorKey>>(new Set());
  const [busyKey, setBusyKey] = useState<ConnectorKey | null>(null);
  const [startedKey, setStartedKey] = useState<ConnectorKey | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);

  const hasOrg =
    typeof window !== "undefined" && !!localStorage.getItem("osai_org_id");
  const [orgName, setOrgName] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [orgBusy, setOrgBusy] = useState(false);
  const [orgError, setOrgError] = useState<string | null>(null);

  const currentKey = CONNECTOR_FLOW[stepIndex];
  const meta = currentKey ? CONNECTOR_META[currentKey] : null;
  const CurrentIcon = currentKey ? getConnectorIcon(currentKey) : null;
  const progress = useMemo(
    () =>
      CONNECTOR_FLOW.map((key) => ({
        key,
        done: phase !== "connect" || stepIndex > CONNECTOR_FLOW.indexOf(key),
      })),
    [phase, stepIndex]
  );

  const advance = useCallback(() => {
    setStartedKey(null);
    setConnectError(null);
    if (stepIndex + 1 < CONNECTOR_FLOW.length) {
      setStepIndex((i) => i + 1);
    } else {
      setPhase(hasOrg ? "done" : "org");
    }
  }, [stepIndex, hasOrg]);

  async function handleConnect(key: ConnectorKey) {
    setBusyKey(key);
    setConnectError(null);
    try {
      const res = await composioConnect(key);
      if (res.redirect_url) {
        window.open(res.redirect_url, "_blank", "noopener,noreferrer");
        setConnected((prev) => new Set(prev).add(key));
        setStartedKey(key);
      } else {
        setConnectError(res.error || "Couldn't start the connection. Try again.");
      }
    } catch {
      setConnectError(
        `${CONNECTOR_META[key]?.label ?? key} isn't available to connect yet. You can skip and add it later.`
      );
    } finally {
      setBusyKey(null);
    }
  }

  async function handleCreateOrg() {
    if (!orgName.trim() || !adminEmail.trim() || !adminName.trim()) {
      setOrgError("Please fill in all fields.");
      return;
    }
    setOrgBusy(true);
    setOrgError(null);
    try {
      const res = await onboardOrg({
        name: orgName.trim(),
        admin_email: adminEmail.trim(),
        admin_display_name: adminName.trim(),
      });
      localStorage.setItem("osai_org_id", res.org_id);
      localStorage.setItem("osai_org_name", res.name);
      localStorage.setItem("osai_user_name", res.admin_display_name);
      try {
        const session = await login({ email: adminEmail.trim() });
        localStorage.setItem("osai_token", session.token);
        localStorage.setItem("osai_user_id", session.user_id);
      } catch {
        /* login optional in some modes */
      }
      setPhase("done");
    } catch {
      setOrgError("Could not create your workspace. Please try again.");
    } finally {
      setOrgBusy(false);
    }
  }

  function finish() {
    localStorage.setItem("osai_onboarded", "true");
    window.location.href = "/ask";
  }

  return (
    <div className="onboarding-root">
      <section className="onboarding-shell" aria-label="First run setup">
        <aside className="onboarding-aside">
          <p className="onboarding-kicker">Workspace setup</p>
          <h1 className="onboarding-heading">
            Start with the tools your team already uses.
          </h1>
          <p className="onboarding-copy">
            Connect a source now, or skip and add it later from Integrations.
            Sheldon keeps every connection optional.
          </p>

          <div className="onboarding-progress" aria-label="Connector setup progress">
            {progress.map((p, i) => {
              const StepIcon = getConnectorIcon(p.key);
              const active = phase === "connect" && i === stepIndex;
              return (
                <div
                  key={p.key}
                  className={cn(
                    "onboarding-progress-item",
                    active && "is-active",
                    p.done && "is-done"
                  )}
                >
                  <span className="onboarding-progress-icon">
                    {p.done ? (
                      <Check className="size-3.5" />
                    ) : (
                      <StepIcon className="size-3.5" strokeWidth={1.8} />
                    )}
                  </span>
                  <span>
                    <span className="onboarding-progress-label">
                      {CONNECTOR_META[p.key]?.label}
                    </span>
                    <span className="onboarding-progress-meta">
                      {p.done ? "Reviewed" : active ? "Current step" : "Optional"}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        </aside>

        <Card className="onboarding-panel">
          {phase === "connect" && meta && currentKey && (
            <div className="onboarding-step">
              <div className="onboarding-step-header">
                <div className="onboarding-step-icon">
                  {CurrentIcon && <CurrentIcon className="size-6" strokeWidth={1.8} />}
                </div>
                <div>
                  <p className="onboarding-step-count">
                    Step {stepIndex + 1} of {CONNECTOR_FLOW.length}
                  </p>
                  <h2 className="onboarding-title">Connect {meta.label}</h2>
                </div>
              </div>
              <p className="onboarding-description">{meta.description}</p>

              {startedKey === currentKey ? (
                <div className="onboarding-actions">
                  <div className="onboarding-success">
                    Authorize {meta.label} in the new tab, then come back and continue.
                  </div>
                  <div className="onboarding-button-stack">
                    <Button onClick={advance} className="w-full">
                      Continue <ArrowRight className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => handleConnect(currentKey)}
                      className="w-full"
                    >
                      Re-open authorization
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="onboarding-button-stack">
                  <Button
                    onClick={() => handleConnect(currentKey)}
                    disabled={busyKey === currentKey}
                    className="w-full"
                  >
                    {busyKey === currentKey ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <>
                        Connect {meta.label} <ArrowRight className="size-4" />
                      </>
                    )}
                  </Button>
                  <Button variant="ghost" onClick={advance} className="w-full">
                    <SkipForward className="size-3.5" /> Skip for now
                  </Button>
                </div>
              )}

              {connectError && <p className="text-xs text-destructive">{connectError}</p>}
              <p className="onboarding-footnote">
                You can connect or disconnect any source later from Integrations.
              </p>
            </div>
          )}

          {phase === "org" && (
            <div className="onboarding-step">
              <div>
                <p className="onboarding-step-count">Workspace details</p>
                <h2 className="onboarding-title">Name your workspace</h2>
                <p className="onboarding-description">
                  This creates your isolated workspace in Sheldon.
                </p>
              </div>
              <div className="space-y-3">
                <Input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Organization name" />
                <Input value={adminName} onChange={(e) => setAdminName(e.target.value)} placeholder="Your name" />
                <Input type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} placeholder="Your work email" />
              </div>
              {orgError && <p className="text-xs text-destructive">{orgError}</p>}
              <Button onClick={handleCreateOrg} disabled={orgBusy} className="w-full">
                {orgBusy ? <Loader2 className="size-4 animate-spin" /> : <>Continue <ArrowRight className="size-4" /></>}
              </Button>
            </div>
          )}

          {phase === "done" && (
            <div className="onboarding-step">
              <div className="onboarding-step-icon is-success">
                <CheckCircle2 className="size-8" />
              </div>
              <div>
                <h2 className="onboarding-title">You're all set</h2>
                <p className="onboarding-description">
                  {connected.size > 0
                    ? `Connected ${connected.size} source${connected.size > 1 ? "s" : ""}. Sheldon is indexing your context now. Ask it anything.`
                    : "You can connect your tools anytime from Integrations. Ask Sheldon is ready when you are."}
                </p>
              </div>
              <Button onClick={finish} className="w-full">
                <Sparkles className="size-4" /> Ask Sheldon your first question
              </Button>
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}
