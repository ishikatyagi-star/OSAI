import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@openuidev/react-ui/components.css";
import "./theme.css";
import "./globals.css";
import AuthWrapper from "../components/auth-wrapper";
import AppShell from "../components/app-shell";

export const metadata: Metadata = {
  title: "Sheldon - Operating System for Company Context",
  description:
    "Connector-first operating layer for scattered company context and execution.",
  icons: {
    icon: "/brand/sheldon-ai-logo.png",
    shortcut: "/brand/sheldon-ai-logo.png",
    apple: "/brand/sheldon-ai-logo.png",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthWrapper>
          <AppShell>{children}</AppShell>
        </AuthWrapper>
      </body>
    </html>
  );
}
