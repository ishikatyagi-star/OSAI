"use client";

import { RecoveryScreen } from "@/components/recovery-screen";

export default function Error({ reset }: { reset: () => void }) {
  return (
    <RecoveryScreen
      title="This workspace hit a problem"
      description="The issue was contained. Try the page again or return to your dashboard."
      retry={reset}
    />
  );
}
