"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getAuthConfig, googleSignInUrl, login, onboardOrg } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"signin" | "onboard">("signin");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Sign-in fields
  const [email, setEmail] = useState("");
  const [googleEnabled, setGoogleEnabled] = useState(false);
  // Password-less email/onboard sign-in may be disabled server-side (prod);
  // default true so local/demo isn't hidden while config is still loading.
  const [emailLoginEnabled, setEmailLoginEnabled] = useState(true);
  const [invitedEmail, setInvitedEmail] = useState("");

  useEffect(() => {
    let cancelled = false;
    // Re-check a few times: the free-tier backend can be cold-starting on the
    // first load, in which case Google may briefly report as unavailable and
    // the sign-in button would otherwise stay hidden.
    (async () => {
      for (let attempt = 0; attempt < 3; attempt++) {
        const c = await getAuthConfig();
        if (cancelled) return;
        setEmailLoginEnabled(c.email_login_enabled);
        if (c.google_enabled) {
          setGoogleEnabled(true);
          return;
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
    })();
    const invite = new URLSearchParams(window.location.search).get("invite");
    if (invite) {
      setInvitedEmail(invite);
      setEmail(invite);
    }
    return () => {
      cancelled = true;
    };
  }, []);

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

        {invitedEmail && (
          <div className="login-error" style={{ background: "var(--green-dim, rgba(34,197,94,0.12))", color: "var(--green)" }}>
            <span>✓</span> You&apos;ve been invited. Sign in with Google using <strong>{invitedEmail}</strong> to join your team.
          </div>
        )}

        {/* Google sign-in (only when configured on the backend) */}
        {googleEnabled && (
          <>
            <button
              type="button"
              onClick={() => {
                window.location.href = googleSignInUrl();
              }}
              className="login-input login-oauth-btn"
            >
              <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden>
                <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/>
                <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.34A9 9 0 0 0 9 18z"/>
                <path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.69 9c0-.6.1-1.18.28-1.72V4.94H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.06l3.01-2.34z"/>
                <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.94l3.01 2.34C4.68 5.16 6.66 3.58 9 3.58z"/>
              </svg>
              Continue with Google
            </button>
            <div className="login-divider">
              <span>or</span>
            </div>
          </>
        )}

        {/* Demo CTA */}
        <button onClick={enterDemo} className="login-demo-btn">
          <span>✨</span>
          <span>Try Demo — no account needed</span>
          <span className="login-demo-arrow">→</span>
        </button>

        {emailLoginEnabled && (
        <>
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
        </>
        )}
      </div>

      {/* Footer */}
      <p className="login-footer">
        By continuing you agree to our <a href="#" style={{ color: "var(--text-secondary)", textDecoration: "underline" }}>Terms of Service</a> and <a href="#" style={{ color: "var(--text-secondary)", textDecoration: "underline" }}>Privacy Policy</a>.
      </p>
    </div>
  );
}
