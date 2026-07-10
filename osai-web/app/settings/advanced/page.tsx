"use client";

import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { EvalDashboard } from "@/components/evals/eval-dashboard";

// Advanced settings - power-user surfaces kept out of the main nav to declutter.
export default function AdvancedSettingsPage() {
  return (
    <div>
      <Link
        href="/settings"
        className="back-link"
      >
        <ChevronLeft className="size-3.5" /> Settings
      </Link>
      <EvalDashboard />
    </div>
  );
}
