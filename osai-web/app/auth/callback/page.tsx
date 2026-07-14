"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import { Loader2 } from "lucide-react";

// Landing page for the Google OAuth round-trip. The backend redirects here with
// the session details in the URL fragment (kept out of server logs). We persist
// them the same way the email login does, then route into the app.
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

    localStorage.setItem("osai_token", token);
    localStorage.setItem("osai_org_id", orgId);
    if (params.get("org_name")) localStorage.setItem("osai_org_name", params.get("org_name")!);
    if (params.get("user_id")) localStorage.setItem("osai_user_id", params.get("user_id")!);
    if (params.get("email")) localStorage.setItem("osai_user_email", params.get("email")!);
    if (params.get("name")) localStorage.setItem("osai_user_name", params.get("name")!);

    // First-ever sign-in → start onboarding (integrations first); else dashboard.
    const isNew = params.get("new") === "1";
    router.replace(isNew ? "/onboarding" : "/dashboard");
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
