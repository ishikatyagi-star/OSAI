"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { login, onboardOrg } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"signin" | "onboard">("signin");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Sign-in fields
  const [email, setEmail] = useState("");

  // Onboard fields
  const [orgName, setOrgName] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");

  function saveSession(token: string, orgId: string, orgN: string, userEmail: string, userName: string) {
    localStorage.setItem("osai_token", token);
    localStorage.setItem("osai_org_id", orgId);
    localStorage.setItem("osai_org_name", orgN);
    localStorage.setItem("osai_user_email", userEmail);
    localStorage.setItem("osai_user_name", userName);
  }

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const session = await login({ email });
      const orgN = session.org_id === "demo-org" ? "OSAI Demo Org" : `Org: ${session.org_id}`;
      saveSession(session.token, session.org_id, orgN, email, "Administrator");
      router.replace("/dashboard");
    } catch {
      setError("No account found for this email. Try onboarding your org first.");
    } finally {
      setLoading(false);
    }
  }

  async function handleOnboard(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await onboardOrg({ name: orgName, admin_email: adminEmail, admin_display_name: adminName });
      const session = await login({ email: adminEmail });
      saveSession(session.token, session.org_id, res.name, adminEmail, res.admin_display_name);
      router.replace("/dashboard");
    } catch {
      setError("Could not create organisation. Please try again or use demo mode.");
    } finally {
      setLoading(false);
    }
  }

  function enterDemo() {
    saveSession("demo-token", "demo-org", "Intellact AI", "admin@intellactai.com", "Admin");
    router.replace("/demo");
  }

  return (
    <div className="login-page">
      {/* Background grid */}
      <div className="login-grid-bg" />

      {/* Nav */}
      <nav className="login-nav">
        <Link href="/" className="login-nav-logo">
          <span className="login-nav-logo-mark">O</span>
          <span>OSAI</span>
        </Link>
        <Link href="/" className="login-nav-back">← Back to site</Link>
      </nav>

      {/* Card */}
      <div className="login-card">
        {/* Header */}
        <div className="login-card-header">
          <div className="login-logo-mark">O</div>
          <h1 className="login-title">Welcome to OSAI</h1>
          <p className="login-subtitle">The operating layer for your company's knowledge</p>
        </div>

        {/* Demo CTA */}
        <button onClick={enterDemo} className="login-demo-btn">
          <span>✨</span>
          <span>Try Demo — no account needed</span>
          <span className="login-demo-arrow">→</span>
        </button>

        <div className="login-divider">
          <span>or continue with your workspace</span>
        </div>

        {/* Tabs */}
        <div className="login-tabs">
          <button
            className={`login-tab${tab === "signin" ? " active" : ""}`}
            onClick={() => { setTab("signin"); setError(""); }}
          >
            Sign In
          </button>
          <button
            className={`login-tab${tab === "onboard" ? " active" : ""}`}
            onClick={() => { setTab("onboard"); setError(""); }}
          >
            New Organisation
          </button>
        </div>

        {error && (
          <div className="login-error">
            <span>⚠</span> {error}
          </div>
        )}

        {tab === "signin" ? (
          <form onSubmit={handleSignIn} className="login-form">
            <div className="login-field">
              <label>Work email</label>
              <input
                type="email"
                required
                placeholder="name@company.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="login-input"
              />
            </div>
            <button type="submit" disabled={loading} className="login-submit">
              {loading ? "Signing in…" : "Continue →"}
            </button>
            <p className="login-hint">
              Don't have an account?{" "}
              <button type="button" onClick={() => setTab("onboard")} className="login-link">
                Onboard your org
              </button>
            </p>
          </form>
        ) : (
          <form onSubmit={handleOnboard} className="login-form">
            <div className="login-field">
              <label>Organisation name</label>
              <input
                type="text"
                required
                placeholder="Acme Corp"
                value={orgName}
                onChange={e => setOrgName(e.target.value)}
                className="login-input"
              />
            </div>
            <div className="login-field">
              <label>Your name</label>
              <input
                type="text"
                required
                placeholder="Jane Doe"
                value={adminName}
                onChange={e => setAdminName(e.target.value)}
                className="login-input"
              />
            </div>
            <div className="login-field">
              <label>Work email</label>
              <input
                type="email"
                required
                placeholder="admin@acme.com"
                value={adminEmail}
                onChange={e => setAdminEmail(e.target.value)}
                className="login-input"
              />
            </div>
            <button type="submit" disabled={loading} className="login-submit">
              {loading ? "Setting up…" : "Create Workspace →"}
            </button>
            <p className="login-hint">
              Already have an account?{" "}
              <button type="button" onClick={() => setTab("signin")} className="login-link">
                Sign in
              </button>
            </p>
          </form>
        )}
      </div>

      {/* Footer */}
      <p className="login-footer">
        By continuing you agree to our Terms of Service and Privacy Policy.
      </p>
    </div>
  );
}
