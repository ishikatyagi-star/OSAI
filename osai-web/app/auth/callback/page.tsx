"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

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
      setTimeout(() => router.replace("/login"), 2000);
      return;
    }

    localStorage.setItem("osai_token", token);
    localStorage.setItem("osai_org_id", orgId);
    if (params.get("user_id")) localStorage.setItem("osai_user_id", params.get("user_id")!);
    if (params.get("email")) localStorage.setItem("osai_user_email", params.get("email")!);
    if (params.get("name")) localStorage.setItem("osai_user_name", params.get("name")!);

    // First-ever sign-in → start onboarding (integrations first); else dashboard.
    const isNew = params.get("new") === "1";
    router.replace(isNew ? "/onboarding" : "/dashboard");
  }, [router]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "#090909",
        gap: 16,
        color: "#aaa",
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 14,
          background:
            "radial-gradient(120% 120% at 25% 15%, #8b6bff 0%, #6a4cf5 45%, #d44df0 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 20,
          fontWeight: 800,
          color: "#fff",
        }}
      >
        O
      </div>
      <p style={{ fontSize: 13 }}>{error || "Signing you in…"}</p>
    </div>
  );
}
