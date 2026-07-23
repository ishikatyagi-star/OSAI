"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { markSignedIn, setSessionCookie } from "@/lib/api";

// Landing page for the Google OAuth round-trip. The backend redirects here with
// the session details in the URL fragment (kept out of server logs). We exchange
// the token for an httpOnly session cookie (so it never lives in localStorage),
// persist only the non-sensitive identity fields, then route into the app.
export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const callbackParamsRef = useRef<URLSearchParams | null>(null);

  useEffect(() => {
    if (!callbackParamsRef.current) {
      const hash = window.location.hash.startsWith("#")
        ? window.location.hash.slice(1)
        : window.location.hash;
      callbackParamsRef.current = new URLSearchParams(hash);
    }
    const params = callbackParamsRef.current;
    // Scrub the bearer token before validation or any network wait. Keep the
    // parsed values in a ref so React Strict Mode can safely re-run this effect.
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}`
    );
    const token = params.get("token");
    const orgId = params.get("org_id");

    if (!token || !orgId) {
      setError("Sign-in did not complete. Please try again.");
      return;
    }

    let cancelled = false;
    let redirectTimer: number | undefined;
    (async () => {
      try {
        // Land the session cookie first-party on this origin (via the /api proxy).
        await setSessionCookie(token);
      } catch {
        if (cancelled) return;
        setError("Sign-in did not complete. Please try again.");
        redirectTimer = window.setTimeout(() => router.replace("/login"), 2000);
        return;
      }
      if (cancelled) return;
      markSignedIn({
        orgId,
        orgName: params.get("org_name") ?? undefined,
        email: params.get("email") ?? undefined,
        name: params.get("name") ?? undefined,
      });
      // First-ever sign-in → onboarding (integrations first); else dashboard.
      router.replace(params.get("new") === "1" ? "/onboarding" : "/dashboard");
    })();

    return () => {
      cancelled = true;
      if (redirectTimer !== undefined) window.clearTimeout(redirectTimer);
    };
  }, [router]);

  return (
    <div className="auth-callback-wrapper">
      <div className="auth-callback-card">
        <Image
          src="/brand/sheldon-ai-logo.png"
          alt="Sheldon"
          width={52}
          height={52}
          className="auth-callback-logo"
          priority
        />
        <h1>{error ? "We couldn’t sign you in" : "Completing sign-in"}</h1>
        {error ? (
          <>
            <p className="text-caption" role="alert">{error}</p>
            <div className="auth-callback-actions">
              <Link href="/login" className="btn btn-primary">Try again</Link>
              <a href="/" className="btn">Back to site</a>
            </div>
          </>
        ) : (
          <div className="auth-callback-status" role="status" aria-live="polite">
            <Loader2 className="animate-spin" size={20} aria-hidden="true" />
            <p className="text-caption">Signing you in…</p>
          </div>
        )}
      </div>
    </div>
  );
}
