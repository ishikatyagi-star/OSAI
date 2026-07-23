"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { AlertTriangle, ArrowRight, Check, Sparkles } from "lucide-react";
import { getAuthConfig, googleSignInUrl, markSignedIn } from "@/lib/api";

// The free-tier API sleeps when idle and refuses connections while it wakes.
// Retry across that window rather than treating the first failure as an answer:
// a single failed check used to latch the page to "sign-in unavailable" until
// the visitor manually reloaded, which is the worst possible first impression
// for someone who came here to sign in.
//
// The window is deliberately longer than the worst cold start we've measured
// (>90s), because giving up early is what produces the false "sign-in is down".
const AUTH_CHECK_ATTEMPTS = 36;
const AUTH_CHECK_RETRY_MS = 5000;

export default function LoginPage() {
  const router = useRouter();
  // Show the button immediately instead of waiting on the backend to confirm it.
  //
  // Gating it on /auth/config made the page as slow as the slowest possible
  // backend: on a cold free-tier instance the visitor stared at a spinner for
  // ~40-90s before a sign-in button appeared, which is what "sign-in takes two
  // minutes to load" actually was. Google sign-in is configured on every real
  // deployment, so assuming it and correcting if the server disagrees is right
  // far more often, and costs nothing when it isn't: the click lands on
  // /auth/google/start, which 503s cleanly if Google really is unconfigured.
  //
  // The config call below still runs: it corrects this to false if the server
  // says so, and it doubles as the request that wakes a sleeping API while the
  // visitor is still reading the page.
  const [googleEnabled, setGoogleEnabled] = useState<boolean | null>(true);
  const [waking, setWaking] = useState(false);
  const [unreachable, setUnreachable] = useState(false);
  const [inviteToken, setInviteToken] = useState("");
  const [oauthReady, setOauthReady] = useState(false);
  const [globalLogoutIncomplete, setGlobalLogoutIncomplete] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setUnreachable(false);
      for (let attempt = 0; attempt < AUTH_CHECK_ATTEMPTS && !cancelled; attempt++) {
        try {
          // strict: a cold-start failure throws instead of masquerading as
          // {google_enabled: false}, so only a real answer ends the loop.
          const c = await getAuthConfig(true);
          if (!cancelled) {
            setWaking(false);
            setGoogleEnabled(c.google_enabled);
          }
          return;
        } catch {
          if (cancelled) return;
          setWaking(true);
          await new Promise((resolve) => setTimeout(resolve, AUTH_CHECK_RETRY_MS));
        }
      }
      // Out of retries and still no answer. We do NOT know that sign-in is
      // disabled - only that the server hasn't replied - so keep googleEnabled
      // null and say exactly that, with a way to try again.
      if (!cancelled) {
        setWaking(false);
        setUnreachable(true);
      }
    })();
    const currentUrl = new URL(window.location.href);
    setGlobalLogoutIncomplete(
      currentUrl.searchParams.get("reason") === "logout_all_failed"
    );
    const fragment = new URLSearchParams(
      currentUrl.hash.startsWith("#") ? currentUrl.hash.slice(1) : currentUrl.hash
    );
    if (fragment.has("invite")) {
      const invite = fragment.get("invite");
      if (invite) setInviteToken(invite);
      // Fragments never reach the frontend server. Remove the capability from
      // browser history as soon as the client has retained it in memory.
      fragment.delete("invite");
      const remainingFragment = fragment.toString();
      window.history.replaceState(
        null,
        "",
        `${currentUrl.pathname}${currentUrl.search}${
          remainingFragment ? `#${remainingFragment}` : ""
        }`
      );
    }
    // The server-rendered page cannot see a URL fragment. Keep the native form
    // inert until hydration has captured it, or an early click could start an
    // ordinary GET sign-in and silently lose the invitation.
    setOauthReady(true);
    return () => {
      cancelled = true;
    };
  }, []);

  // Demo workspace = shared sample data, no real account. Real sign-in is
  // Google only - the passwordless email login accepted any address without
  // verification, so it was removed.
  function enterDemo() {
    // Demo has no real session/cookie - it's the public demo-org reached via the
    // X-Org-Id header. Mark authed locally so the app shell renders; server-side
    // writes still 403 by design (the demo workspace is read-only).
    markSignedIn({
      orgId: "demo-org",
      orgName: "Intellact AI",
      email: "admin@intellactai.com",
      name: "Admin",
    });
    router.replace("/demo");
  }

  return (
    <div className="login-page">
      {/* Background grid */}
      <div className="login-grid-bg" />

      {/* Nav */}
      <nav className="login-nav">
        <a href="/" className="login-nav-logo" aria-label="Sheldon home">
          <Image src="/brand/sheldon-ai-logo.png" alt="" width={28} height={28} className="login-nav-logo-mark" priority />
          <span>Sheldon</span>
        </a>
        <a href="/" className="login-nav-back">← Back to site</a>
      </nav>

      {/* Card */}
      <div className="login-card">
        {/* Header */}
        <div className="login-card-header">
          <Image src="/brand/sheldon-ai-logo.png" alt="Sheldon" width={52} height={52} className="login-logo-mark" priority />
          <h1 className="login-title">Welcome to Sheldon</h1>
          <p className="login-subtitle">The operating layer for your company&apos;s knowledge</p>
        </div>

        {inviteToken && (
          <div className="login-error" style={{ background: "var(--green-dim, rgba(34,197,94,0.12))", color: "var(--green)" }}>
            <Check className="size-3.5" /> You&apos;ve been invited. Sign in with the Google account that received this link to join your team.
          </div>
        )}

        {/* Google sign-in (only when configured on the backend) */}
        {googleEnabled && (
          <form
            action={googleSignInUrl()}
            method={inviteToken ? "post" : "get"}
            target="_self"
          >
            {inviteToken && (
              <input type="hidden" name="invite" value={inviteToken} />
            )}
            <button
              type="submit"
              disabled={!oauthReady}
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
          </form>
        )}

        {globalLogoutIncomplete && (
          <div className="login-error" role="alert">
            <AlertTriangle className="size-3.5" /> This device is signed out, but Sheldon could
            not confirm that your other sessions were revoked. Sign in again and retry Sign out
            everywhere.
          </div>
        )}
        {/* The server answered and said Google is not configured here. */}
        {googleEnabled === false && (
          <div className="login-error" role="status">
            <AlertTriangle className="size-3.5" /> Google sign-in is not enabled on this deployment. You can still explore the demo.
          </div>
        )}

        {/* A slow or unreachable backend is a note under a usable button, not a
            blocker in front of it. The button already works: clicking it wakes
            the API on the way to Google. Never hide sign-in just because we
            couldn't reach the server - that is the failure this page had. */}
        {googleEnabled !== false && (waking || unreachable) && (
          <p className="login-auth-check" role="status" aria-live="polite">
            {unreachable
              ? "The server is taking a while to wake up. Sign-in still works; the first click may be slow."
              : "Waking up the server. The first sign-in after a quiet spell can take a moment."}
          </p>
        )}

        {googleEnabled && (
          <div className="login-divider">
            <span>or</span>
          </div>
        )}

        {/* Demo CTA */}
        <button type="button" onClick={enterDemo} className="login-demo-btn">
          <Sparkles className="size-4" />
          <span>Try Demo - no account needed</span>
          <ArrowRight className="login-demo-arrow size-4" />
        </button>
      </div>

    </div>
  );
}
