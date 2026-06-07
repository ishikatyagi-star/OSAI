import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import AuthWrapper from "../components/auth-wrapper";
import AppShell from "../components/app-shell";

export const metadata: Metadata = {
  title: "OSAI — Operating System for Company Context",
  description:
    "Connector-first operating layer for scattered company context and execution.",
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
