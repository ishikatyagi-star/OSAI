"use client";

import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { EvalDashboard } from "@/components/evals/eval-dashboard";

export default function EvalsPage() {
  return (
    <div>
      <Link href="/settings" className="back-link">
        <ChevronLeft className="size-3.5" aria-hidden="true" /> Settings
      </Link>
      <EvalDashboard />
    </div>
  );
}
