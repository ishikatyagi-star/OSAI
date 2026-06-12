"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

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
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "#090909",
        gap: 20,
      }}
    >
      {/* Logo mark */}
      <div
        style={{
          width: 52,
          height: 52,
          borderRadius: 16,
          background:
            "radial-gradient(120% 120% at 25% 15%, #8b6bff 0%, #6a4cf5 45%, #d44df0 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 24,
          fontWeight: 800,
          color: "#fff",
          letterSpacing: -1,
          boxShadow: "0 0 40px rgba(106,76,245,0.4)",
        }}
      >
        O
      </div>

      <div style={{ textAlign: "center" }}>
        <p
          style={{
            fontFamily: "monospace",
            fontSize: 12,
            color: "#999999",
            fontWeight: 600,
            letterSpacing: 2,
            textTransform: "uppercase",
            marginBottom: 6,
          }}
        >
          Entering Demo
        </p>
        <p style={{ fontSize: 13, color: "#6a6a6a" }}>
          Loading Intellact AI workspace…
        </p>
      </div>

      {/* Animated dots */}
      <div style={{ display: "flex", gap: 6 }}>
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "#ffffff",
              animation: "pulse 1.2s ease-in-out infinite",
              animationDelay: `${i * 0.2}s`,
              opacity: 0.4,
            }}
          />
        ))}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.2; transform: scale(0.8); }
          50% { opacity: 1; transform: scale(1.2); }
        }
      `}</style>
    </div>
  );
}
