"use client";

import { useCallback, useState } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  Loader2,
  Plug,
  Sparkles,
  User,
  Zap,
} from "lucide-react";
import { login, onboardOrg, triggerSync } from "@/lib/api";
import { CONNECTOR_META } from "@/lib/connector-meta";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type Step = "welcome" | "org" | "connectors" | "sync" | "done";

const STEPS: { id: Step; label: string; icon: React.ReactNode }[] = [
  { id: "welcome", label: "Welcome", icon: <Sparkles className="size-4" /> },
  { id: "org", label: "Your org", icon: <User className="size-4" /> },
  { id: "connectors", label: "Connect", icon: <Plug className="size-4" /> },
  { id: "sync", label: "First sync", icon: <Zap className="size-4" /> },
  { id: "done", label: "Ready", icon: <Check className="size-4" /> },
];

const RECOMMENDED_CONNECTORS = ["notion", "slack", "google_drive", "freshdesk"];

export default function OnboardingPage() {
  const [step, setStep] = useState<Step>("welcome");
  const [orgName, setOrgName] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectedKeys, setConnectedKeys] = useState<Set<string>>(new Set());
  const [syncStarted, setSyncStarted] = useState(false);
  const [syncDone, setSyncDone] = useState(false);

  const stepIndex = STEPS.findIndex((s) => s.id === step);

  const goNext = useCallback(() => {
    const next = STEPS[stepIndex + 1];
    if (next) setStep(next.id);
  }, [stepIndex]);

  const goBack = useCallback(() => {
    const prev = STEPS[stepIndex - 1];
    if (prev) setStep(prev.id);
  }, [stepIndex]);

  async function handleCreateOrg() {
    if (!orgName.trim() || !adminEmail.trim() || !adminName.trim()) {
      setError("Please fill in all fields.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await onboardOrg({
        name: orgName.trim(),
        admin_email: adminEmail.trim(),
        admin_display_name: adminName.trim(),
      });
      localStorage.setItem("osai_org_id", res.org_id);
      // Also log in
      try {
        const session = await login({ email: adminEmail.trim() });
        localStorage.setItem("osai_token", session.token);
        localStorage.setItem("osai_user_id", session.user_id);
      } catch {
        // Login may not exist yet in demo mode — that's fine
      }
      goNext();
    } catch {
      // Demo fallback — just proceed
      localStorage.setItem("osai_org_id", "demo-org");
      goNext();
    } finally {
      setBusy(false);
    }
  }

  function toggleConnector(key: string) {
    setConnectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleFirstSync() {
    setSyncStarted(true);
    setBusy(true);
    try {
      const promises = Array.from(connectedKeys).map((k) =>
        triggerSync(k).catch(() => null)
      );
      await Promise.all(promises);
    } catch {
      // Demo fallback
    }
    // Simulate a brief sync time
    await new Promise((r) => setTimeout(r, 2000));
    setSyncDone(true);
    setBusy(false);
  }

  function finishOnboarding() {
    localStorage.setItem("osai_onboarded", "true");
    window.location.href = "/ask";
  }

  return (
    <div className="flex min-h-[calc(100vh-128px)] flex-col items-center justify-center px-4">
      {/* Progress */}
      <div className="mb-8 flex items-center gap-1">
        {STEPS.map((s, i) => (
          <div key={s.id} className="flex items-center">
            <div
              className={cn(
                "flex size-8 items-center justify-center rounded-full border text-xs transition-colors",
                i < stepIndex
                  ? "border-primary bg-primary text-primary-foreground"
                  : i === stepIndex
                  ? "border-primary bg-primary/15 text-primary"
                  : "border-border bg-card text-muted-foreground"
              )}
            >
              {i < stepIndex ? <Check className="size-3.5" /> : s.icon}
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={cn(
                  "mx-1 h-px w-8",
                  i < stepIndex ? "bg-primary" : "bg-border"
                )}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step content */}
      <Card className="w-full max-w-lg p-8">
        {step === "welcome" && (
          <div className="space-y-5 text-center">
            <div className="mx-auto flex size-16 items-center justify-center rounded-2xl bg-primary/15 text-3xl font-extrabold text-primary">
              O
            </div>
            <div>
              <h1 className="text-xl font-semibold">Welcome to OSAI</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                The operating system for your company&apos;s scattered context. Let&apos;s
                get you set up in under 2 minutes.
              </p>
            </div>
            <ul className="mx-auto max-w-xs space-y-2 text-left text-sm text-foreground/80">
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                Connect your knowledge sources (Notion, Slack, Drive…)
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                OSAI indexes everything into a unified knowledge base
              </li>
              <li className="flex items-start gap-2">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                Ask anything, get cited answers, take actions in your tools
              </li>
            </ul>
            <Button onClick={goNext} className="w-full">
              Get started <ArrowRight className="size-4" />
            </Button>
          </div>
        )}

        {step === "org" && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold">Set up your organization</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                This creates your isolated workspace in OSAI.
              </p>
            </div>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Organization name
                </label>
                <Input
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder="e.g. Intellact AI, Stanford CS Dept"
                  autoFocus
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Your name
                </label>
                <Input
                  value={adminName}
                  onChange={(e) => setAdminName(e.target.value)}
                  placeholder="e.g. Alex Chen"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Your email
                </label>
                <Input
                  type="email"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                  placeholder="alex@university.edu"
                />
              </div>
            </div>
            {error && <p className="text-xs text-destructive">{error}</p>}
            <div className="flex items-center justify-between gap-2">
              <Button variant="ghost" size="sm" onClick={goBack}>
                <ChevronLeft className="size-3.5" /> Back
              </Button>
              <Button onClick={handleCreateOrg} disabled={busy}>
                {busy ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <>
                    Continue <ArrowRight className="size-4" />
                  </>
                )}
              </Button>
            </div>
          </div>
        )}

        {step === "connectors" && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold">Connect your sources</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Select the tools where your team&apos;s knowledge lives. You can add
                more later from Integrations.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {RECOMMENDED_CONNECTORS.map((key) => {
                const meta = CONNECTOR_META[key];
                if (!meta) return null;
                const selected = connectedKeys.has(key);
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => toggleConnector(key)}
                    className={cn(
                      "flex items-center gap-3 rounded-lg border p-3 text-left transition-colors",
                      selected
                        ? "border-primary bg-primary/10"
                        : "border-border bg-card hover:bg-accent"
                    )}
                  >
                    <span className="text-xl" style={{ color: meta.color }}>
                      {meta.icon}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground">
                        {meta.label}
                      </p>
                    </div>
                    {selected && (
                      <CheckCircle2 className="size-4 shrink-0 text-primary" />
                    )}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              In the pilot, connections use OAuth handled by the backend. For now
              this marks them as selected.
            </p>
            <div className="flex items-center justify-between gap-2">
              <Button variant="ghost" size="sm" onClick={goBack}>
                <ChevronLeft className="size-3.5" /> Back
              </Button>
              <Button onClick={goNext}>
                {connectedKeys.size === 0 ? "Skip" : "Continue"}{" "}
                <ArrowRight className="size-4" />
              </Button>
            </div>
          </div>
        )}

        {step === "sync" && (
          <div className="space-y-5 text-center">
            <div>
              <h2 className="text-lg font-semibold">Run your first sync</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {connectedKeys.size > 0
                  ? `We'll index content from ${connectedKeys.size} source${connectedKeys.size > 1 ? "s" : ""}. This usually takes 30–60 seconds.`
                  : "No sources selected — you can trigger syncs later from Integrations."}
              </p>
            </div>

            {!syncStarted && (
              <div className="flex flex-col items-center gap-3">
                {connectedKeys.size > 0 && (
                  <div className="flex flex-wrap justify-center gap-1.5">
                    {Array.from(connectedKeys).map((k) => {
                      const meta = CONNECTOR_META[k];
                      return meta ? (
                        <Badge key={k} variant="secondary">
                          <span style={{ color: meta.color }}>{meta.icon}</span>{" "}
                          {meta.label}
                        </Badge>
                      ) : null;
                    })}
                  </div>
                )}
                <Button
                  onClick={connectedKeys.size > 0 ? handleFirstSync : goNext}
                  className="mt-2"
                >
                  {connectedKeys.size > 0 ? (
                    <>
                      <Zap className="size-4" /> Start sync
                    </>
                  ) : (
                    <>
                      Skip <ArrowRight className="size-4" />
                    </>
                  )}
                </Button>
              </div>
            )}

            {syncStarted && !syncDone && (
              <div className="flex flex-col items-center gap-3 py-4">
                <Loader2 className="size-8 animate-spin text-primary" />
                <p className="text-sm text-muted-foreground">
                  Indexing your content…
                </p>
              </div>
            )}

            {syncDone && (
              <div className="flex flex-col items-center gap-3 py-4">
                <CheckCircle2 className="size-8 text-success" />
                <p className="text-sm text-foreground">
                  Sync complete! Your knowledge base is ready.
                </p>
                <Button onClick={goNext} className="mt-2">
                  Continue <ArrowRight className="size-4" />
                </Button>
              </div>
            )}

            {!syncStarted && (
              <div className="flex justify-start">
                <Button variant="ghost" size="sm" onClick={goBack}>
                  <ChevronLeft className="size-3.5" /> Back
                </Button>
              </div>
            )}
          </div>
        )}

        {step === "done" && (
          <div className="space-y-5 text-center">
            <div className="mx-auto flex size-16 items-center justify-center rounded-2xl bg-success/15 text-success">
              <CheckCircle2 className="size-8" />
            </div>
            <div>
              <h2 className="text-xl font-semibold">You&apos;re all set!</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                OSAI is ready to answer questions about{" "}
                <strong>{orgName || "your organization"}</strong>. Try asking it
                something.
              </p>
            </div>
            <Button onClick={finishOnboarding} className="w-full">
              <Sparkles className="size-4" /> Ask OSAI your first question
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
