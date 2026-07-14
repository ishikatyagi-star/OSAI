"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, CheckCircle2, Loader2, Plug, Sparkles } from "lucide-react";
import { login, onboardOrg } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { SheldonMascot } from "@/components/sheldon-mascot";

type Phase = "org" | "done";

export default function OnboardingPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("org");
  const [ready, setReady] = useState(false);

  const [orgName, setOrgName] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [orgBusy, setOrgBusy] = useState(false);
  const [orgError, setOrgError] = useState<string | null>(null);

  useEffect(() => {
    setPhase(localStorage.getItem("osai_org_id") ? "done" : "org");
    setReady(true);
  }, []);

  async function handleCreateOrg(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
        // login() lands the httpOnly session cookie; the JWT itself must never
        // be persisted in localStorage (QA E-03).
        const session = await login({ email: adminEmail.trim() });
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

  // Land new users straight on the full connector catalog (1,000+ apps via
  // Composio) rather than a fixed wizard of a handful of tools.
  function connectTools() {
    localStorage.setItem("osai_onboarded", "true");
    router.push("/integrations?catalog=1");
  }

  function skipToAsk() {
    localStorage.setItem("osai_onboarded", "true");
    router.push("/ask");
  }

  if (!ready) {
    return (
      <div className="onboarding-root">
        <div className="async-state" role="status" aria-live="polite">
          <Loader2 className="size-5 animate-spin" aria-hidden="true" />
          Preparing your workspace…
        </div>
      </div>
    );
  }

  return (
    <div className="onboarding-root">
      <section className="onboarding-shell" aria-label="First run setup">
        <aside className="onboarding-aside">
          <p className="onboarding-kicker">Workspace setup</p>
          <h1 className="onboarding-heading">
            Bring your company context into Sheldon.
          </h1>
          <p className="onboarding-copy">
            Create your workspace, then connect any of 1,000+ tools your team
            already uses. Every connection is optional and can be added or
            removed anytime from Integrations.
          </p>
          <SheldonMascot
            state={phase === "done" ? "happy" : "orchestrating"}
            size={132}
            className="onboarding-mascot"
            priority
          />
        </aside>

        <Card className="onboarding-panel">
          {phase === "org" && (
            <form className="onboarding-step" onSubmit={handleCreateOrg}>
              <div>
                <p className="onboarding-step-count">Workspace details</p>
                <h2 className="onboarding-title">Name your workspace</h2>
                <p className="onboarding-description">
                  This creates your isolated workspace in Sheldon.
                </p>
              </div>
              <div className="space-y-3">
                <label className="onboarding-field" htmlFor="organization-name">
                  <span>Organization name</span>
                  <Input id="organization-name" name="organization" autoComplete="organization" required value={orgName} onChange={(e) => setOrgName(e.target.value)} />
                </label>
                <label className="onboarding-field" htmlFor="admin-name">
                  <span>Your name</span>
                  <Input id="admin-name" name="name" autoComplete="name" required value={adminName} onChange={(e) => setAdminName(e.target.value)} />
                </label>
                <label className="onboarding-field" htmlFor="admin-email">
                  <span>Your work email</span>
                  <Input id="admin-email" name="email" type="email" autoComplete="email" required value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} />
                </label>
              </div>
              {orgError && <p className="text-xs text-destructive" role="alert">{orgError}</p>}
              <Button type="submit" disabled={orgBusy} className="w-full">
                {orgBusy ? <Loader2 className="size-4 animate-spin" /> : <>Continue <ArrowRight className="size-4" /></>}
              </Button>
            </form>
          )}

          {phase === "done" && (
            <div className="onboarding-step">
              <div className="onboarding-step-icon is-success">
                <CheckCircle2 className="size-8" />
              </div>
              <div>
                <h2 className="onboarding-title">Your workspace is ready</h2>
                <p className="onboarding-description">
                  Connect the tools your team uses so Sheldon can index your
                  context, or jump straight into asking.
                </p>
              </div>
              <div className="onboarding-button-stack">
                <Button onClick={connectTools} className="w-full">
                  <Plug className="size-4" /> Connect your tools
                </Button>
                <Button variant="ghost" onClick={skipToAsk} className="w-full">
                  <Sparkles className="size-4" /> Skip for now, go to Ask Sheldon
                </Button>
              </div>
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}
