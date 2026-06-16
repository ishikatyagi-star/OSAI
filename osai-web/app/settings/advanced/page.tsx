"use client";

import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { EvalDashboard } from "@/components/evals/eval-dashboard";

// Advanced settings — power-user surfaces kept out of the main nav to declutter.
export default function AdvancedSettingsPage() {
  return (
    <div>
      <Link
        href="/settings"
        className="meta"
        style={{ display: "inline-flex", alignItems: "center", gap: 4, marginBottom: 12 }}
      >
        <ChevronLeft className="size-3.5" /> Settings
      </Link>
      <EvalDashboard />
    </div>
  );
}
