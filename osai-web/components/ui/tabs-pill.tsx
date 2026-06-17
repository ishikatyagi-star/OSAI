"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";

import { cn } from "@/lib/utils";

const TabsPill = TabsPrimitive.Root;

function TabsPillList({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-pill-list"
      className={cn("tabs-pill-list", className)}
      {...props}
    />
  );
}

function TabsPillTrigger({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-pill-trigger"
      className={cn("tabs-pill-trigger", className)}
      {...props}
    />
  );
}

function TabsPillContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-pill-content"
      className={cn("mt-4", className)}
      {...props}
    />
  );
}

export { TabsPill, TabsPillList, TabsPillTrigger, TabsPillContent };
