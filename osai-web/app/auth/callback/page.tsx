"use client";

import { useEffect, useState } from "react";
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

  useEffect(() => {
    const hash = window.location.hash.startsWith("#")
      ? window.location.hash.slice(1)
      : window.location.hash;
    const params = new URLSearchParams(hash);
    const token = params.get("token");
    const orgId = params.get("org_id");

    if (!token || !orgId) {
      setError("Sign-in did not complete. Please try again.");
      return;
    }

    (async () => {
      try {
        // Land the session cookie first-party on this origin (via the /api proxy).
        await setSessionCookie(token);
      } catch {
        setError("Sign-in did not complete. Please try again.");
        setTimeout(() => router.replace("/login"), 2000);
        return;
      }
      markSignedIn({
        orgId,
        orgName: params.get("org_name") ?? undefined,
        email: params.get("email") ?? undefined,
        name: params.get("name") ?? undefined,
      });
      // Drop the token from the URL so it isn't left in history.
      window.history.replaceState(null, "", window.location.pathname);
      // First-ever sign-in → onboarding (integrations first); else dashboard.
      router.replace(params.get("new") === "1" ? "/onboarding" : "/dashboard");
    })();
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
              <Link href="/" className="btn">Back to site</Link>
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
