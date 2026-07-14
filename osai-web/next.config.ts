import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";
// The browser must be allowed to call the backend API host; everything else is
// same-origin. Falls back to localhost for dev.
const apiOrigin =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Content-Security-Policy. script/style keep 'unsafe-inline' because Next.js
// injects an inline hydration bootstrap and Tailwind emits inline styles;
// tightening these to a nonce is the stricter follow-up. The high-value
// directives (frame-ancestors, object-src, base-uri, form-action) are locked
// down here so clickjacking and base-tag/redirect injection are closed now.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  // Google Fonts: stylesheet from fonts.googleapis.com, font files from
  // fonts.gstatic.com (the marketing/landing pages use them).
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "img-src 'self' data: blob:",
  "font-src 'self' data: https://fonts.gstatic.com",
  `connect-src 'self' ${apiOrigin}${isDev ? " ws: http://localhost:8000" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
]
  .join("; ")
  .trim();

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  // HSTS only matters over HTTPS (prod); harmless-but-pointless on localhost.
  ...(isDev
    ? []
    : [
        {
          key: "Strict-Transport-Security",
          value: "max-age=63072000; includeSubDomains; preload",
        },
      ]),
];

const nextConfig: NextConfig = {
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
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
