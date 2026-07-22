"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

type StatusDotState = "connected" | "error" | "disconnected" | (string & {});

interface StatusDotProps extends React.HTMLAttributes<HTMLSpanElement> {
  state: StatusDotState;
}

function StatusDot({ state, className, ...props }: StatusDotProps) {
  const modifier =
    state === "connected"
      ? "status-dot--connected"
      : state === "error"
        ? "status-dot--error"
        : "status-dot--default";

  return (
    <span
      className={cn("status-dot", modifier, className)}
      role="img"
      aria-label={state}
      {...props}
    />
  );
}

export { StatusDot };
export type { StatusDotProps, StatusDotState };
