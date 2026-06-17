"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

export default function DemoPage() {
  const router = useRouter();

  useEffect(() => {
    // Set demo credentials in localStorage
    localStorage.setItem("osai_token", "demo-token");
    localStorage.setItem("osai_org_id", "demo-org");
    localStorage.setItem("osai_org_name", "Intellact AI");
    localStorage.setItem("osai_user_email", "admin@intellactai.com");
    localStorage.setItem("osai_user_name", "Admin");

    // Redirect to dashboard
    router.replace("/dashboard");
  }, [router]);

  return (
    <div className="demo-loading-page">
      {/* Logo mark */}
      <div className="demo-logo-mark">O</div>

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
