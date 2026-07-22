"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import Image from "next/image";
import { clearServerSessionCookie } from "@/lib/api";

export default function DemoPage() {
  const router = useRouter();

  useEffect(() => {
    // Mark the shared demo workspace locally. Only non-sensitive display flags
    // are stored - no token key at all (QA E-03): demo auth is the X-Org-Id
    // header, and real sessions live in the httpOnly cookie.
    localStorage.removeItem("osai_token"); // legacy key from older builds
    localStorage.setItem("osai_authed", "1");
    localStorage.setItem("osai_org_id", "demo-org");
    localStorage.setItem("osai_org_name", "Intellact AI");
    localStorage.setItem("osai_user_email", "admin@intellactai.com");
    localStorage.setItem("osai_user_name", "Admin");

    // Demo requests omit credentials immediately. Also remove any pre-existing
    // real httpOnly session cookie so leaving demo cannot silently revive it.
    void clearServerSessionCookie().catch(() => {});

    // Redirect to dashboard
    router.replace("/dashboard");
  }, [router]);

  return (
    <div className="demo-loading-page">
      {/* Logo mark */}
      <Image src="/brand/sheldon-ai-logo.png" alt="Sheldon" width={52} height={52} className="demo-logo-mark" priority />

      <div className="demo-text-group">
        <p className="demo-label">Entering Demo</p>
        <p className="demo-description">
          Loading Intellact AI workspace&hellip;
        </p>
      </div>

      {/* Spinner */}
      <Loader2 size={20} className="demo-spinner" />
    </div>
  );
}
