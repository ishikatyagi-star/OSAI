"use client";

import { RecoveryScreen } from "@/components/recovery-screen";

export default function GlobalError({ reset }: { reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <RecoveryScreen
          title="Sheldon AI could not start"
          description="Try again in a moment. If this keeps happening, return to the dashboard."
          retry={reset}
        />
      </body>
    </html>
  );
}
