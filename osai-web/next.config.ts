import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Deep-link aliases so URLs matching the sidebar labels resolve to the real
  // routes instead of 404-ing (e.g. /context-inbox → /inbox).
  async redirects() {
    return [
      { source: "/context-inbox", destination: "/inbox", permanent: true },
      { source: "/decision-log", destination: "/decisions", permanent: true },
      { source: "/team-board", destination: "/board", permanent: true },
      { source: "/org-graph", destination: "/graph", permanent: true },
      { source: "/data-routing", destination: "/settings/data-routing", permanent: true },
    ];
  },
};

export default nextConfig;
