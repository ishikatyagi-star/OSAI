"use client";

import Link from "next/link";

type RecoveryScreenProps = {
  title: string;
  description: string;
  retry?: () => void;
};

export function RecoveryScreen({ title, description, retry }: RecoveryScreenProps) {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        background: "var(--bg-primary, #f5f5f5)",
      }}
    >
      <section
        style={{
          width: "min(100%, 480px)",
          padding: 32,
          border: "1px solid var(--border, #deded8)",
          borderRadius: 20,
          background: "var(--bg-surface, #ffffff)",
          textAlign: "center",
        }}
      >
        <p style={{ margin: "0 0 12px", fontWeight: 700 }}>Sheldon AI</p>
        <h1 style={{ margin: "0 0 12px", color: "var(--text-primary, #1d1d1b)" }}>{title}</h1>
        <p style={{ margin: "0 0 24px", color: "var(--text-secondary, #686862)", lineHeight: 1.5 }}>
          {description}
        </p>
        <div style={{ display: "flex", justifyContent: "center", gap: 12, flexWrap: "wrap" }}>
          {retry && (
            <button type="button" onClick={retry} className="btn-primary">
              Try again
            </button>
          )}
          <Link href="/dashboard" className="btn-secondary">
            Go to dashboard
          </Link>
        </div>
      </section>
    </main>
  );
}
