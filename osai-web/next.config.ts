import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/", destination: "/landing" }];
  },
  // Deep-link aliases resolve legacy labels to canonical live surfaces.
  async redirects() {
    return [
      { source: "/context-inbox", destination: "/ask", permanent: true },
      { source: "/inbox", destination: "/ask", permanent: true },
      { source: "/decision-log", destination: "/decisions", permanent: true },
      { source: "/team-board", destination: "/board", permanent: true },
      { source: "/org-graph", destination: "/graph", permanent: true },
      { source: "/data-routing", destination: "/team", permanent: true },
      { source: "/settings/data-routing", destination: "/team", permanent: true },
      // Workflows folded into Automations (transcript-extraction is now a mode there).
      { source: "/workflows", destination: "/automations", permanent: true },
    ];
  },
};

export default nextConfig;
