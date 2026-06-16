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
import { login, onboardOrg, triggerSync } from "@/lib/api";
import { CONNECTOR_META } from "@/lib/connector-meta";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// Integrations come FIRST and are stepped through one at a time so the user can
// connect (or skip) each source deliberately. Order = highest-value first.
const CONNECTOR_FLOW = ["notion", "google_drive", "slack", "freshdesk"] as const;

type ConnectorKey = (typeof CONNECTOR_FLOW)[number];
type Phase = "connect" | "org" | "done";

export default function OnboardingPage() {
  const [phase, setPhase] = useState<Phase>("connect");
  const [stepIndex, setStepIndex] = useState(0);
  const [connected, setConnected] = useState<Set<ConnectorKey>>(new Set());
  const [busyKey, setBusyKey] = useState<ConnectorKey | null>(null);

  // Org details only needed if we don't already have a workspace (e.g. the user
  // didn't arrive via Google sign-in, which provisions one automatically).
  const hasOrg =
    typeof window !== "undefined" && !!localStorage.getItem("osai_org_id");
  const [orgName, setOrgName] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [orgBusy, setOrgBusy] = useState(false);
  const [orgError, setOrgError] = useState<string | null>(null);

  const currentKey = CONNECTOR_FLOW[stepIndex];
  const meta = currentKey ? CONNECTOR_META[currentKey] : null;
  const progress = useMemo(
    () => CONNECTOR_FLOW.map((k) => ({ key: k, done: stepIndex > CONNECTOR_FLOW.indexOf(k) })),
    [stepIndex]
  );

  const advance = useCallback(() => {
    if (stepIndex + 1 < CONNECTOR_FLOW.length) {
      setStepIndex((i) => i + 1);
    } else {
      setPhase(hasOrg ? "done" : "org");
    }
  }, [stepIndex, hasOrg]);

  async function handleConnect(key: ConnectorKey) {
    setBusyKey(key);
    try {
      // Optimistically mark connected and kick a first sync (best-effort). Full
      // OAuth handshakes are completed later from Integrations if required.
      await triggerSync(key).catch(() => null);
      setConnected((prev) => new Set(prev).add(key));
    } finally {
      setBusyKey(null);
      advance();
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
    <div className="flex min-h-[calc(100vh-128px)] flex-col items-center justify-center px-4">
      {/* Connector progress rail (only during the connect phase) */}
      {phase === "connect" && (
        <div className="mb-8 flex items-center gap-1">
          {progress.map((p, i) => (
            <div key={p.key} className="flex items-center">
              <div
                className={cn(
                  "flex size-8 items-center justify-center rounded-full border text-base transition-colors",
                  p.done
                    ? "border-primary bg-primary text-primary-foreground"
                    : i === stepIndex
                    ? "border-primary bg-primary/15"
                    : "border-border bg-card opacity-60"
                )}
                title={CONNECTOR_META[p.key]?.label}
              >
                {p.done ? <Check className="size-3.5" /> : CONNECTOR_META[p.key]?.icon}
              </div>
              {i < progress.length - 1 && (
                <div className={cn("mx-1 h-px w-8", p.done ? "bg-primary" : "bg-border")} />
              )}
            </div>
          ))}
        </div>
      )}

      <Card className="w-full max-w-lg p-8">
        {/* PHASE: connect one source at a time */}
        {phase === "connect" && meta && currentKey && (
          <div className="space-y-5 text-center">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Step {stepIndex + 1} of {CONNECTOR_FLOW.length} · Connect your tools
            </p>
            <div
              className="mx-auto flex size-16 items-center justify-center rounded-2xl text-4xl"
              style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
            >
              {meta.icon}
            </div>
            <div>
              <h1 className="text-xl font-semibold">Connect {meta.label}</h1>
              <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
                {meta.description}
              </p>
            </div>
            <div className="flex flex-col gap-2">
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
            <p className="text-xs text-muted-foreground">
              You can connect or disconnect any source later from Integrations.
            </p>
          </div>
        )}

        {/* PHASE: minimal org details (only if not already provisioned) */}
        {phase === "org" && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold">Name your workspace</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                This creates your isolated workspace in OSAI.
              </p>
            </div>
            <div className="space-y-3">
              <Input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Organization name" autoFocus />
              <Input value={adminName} onChange={(e) => setAdminName(e.target.value)} placeholder="Your name" />
              <Input type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} placeholder="Your work email" />
            </div>
            {orgError && <p className="text-xs text-destructive">{orgError}</p>}
            <Button onClick={handleCreateOrg} disabled={orgBusy} className="w-full">
              {orgBusy ? <Loader2 className="size-4 animate-spin" /> : <>Continue <ArrowRight className="size-4" /></>}
            </Button>
          </div>
        )}

        {/* PHASE: done */}
        {phase === "done" && (
          <div className="space-y-5 text-center">
            <div className="mx-auto flex size-16 items-center justify-center rounded-2xl bg-success/15 text-success">
              <CheckCircle2 className="size-8" />
            </div>
            <div>
              <h2 className="text-xl font-semibold">You&apos;re all set!</h2>
              <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
                {connected.size > 0
                  ? `Connected ${connected.size} source${connected.size > 1 ? "s" : ""}. OSAI is indexing your context now — ask it anything.`
                  : "You can connect your tools anytime from Integrations. Ask OSAI is ready when you are."}
              </p>
            </div>
            <Button onClick={finish} className="w-full">
              <Sparkles className="size-4" /> Ask OSAI your first question
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
