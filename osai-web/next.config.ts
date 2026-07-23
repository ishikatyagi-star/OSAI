import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";
// The browser must be allowed to call the backend API host; everything else is
// same-origin. Localhost is a development fallback only: a production build
// with a missing API origin must fail instead of shipping a broken proxy.
const configuredApiOrigin = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
if (!isDev && !configuredApiOrigin) {
  throw new Error("NEXT_PUBLIC_API_BASE_URL is required for production builds");
}
function normalizeApiOrigin(value: string): string {
  const parsed = new URL(value);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must use http or https");
  }
  if (
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash ||
    (parsed.pathname && parsed.pathname !== "/")
  ) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be an origin without credentials or a path");
  }
  return parsed.origin;
}
const apiOrigin = configuredApiOrigin
  ? normalizeApiOrigin(configuredApiOrigin)
  : "http://localhost:8000";

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
  `connect-src 'self' ${apiOrigin} https://fonts.googleapis.com https://fonts.gstatic.com${isDev ? " ws: http://localhost:8000" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  // The invite form posts only to the API. Chromium also applies form-action
  // to its 303 destination, so the exact Google authorization origin must be
  // present or the otherwise-valid OAuth redirect is blocked after submission.
  `form-action 'self' ${apiOrigin} https://accounts.google.com`,
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
    return [
      { source: "/", destination: "/landing" },
      // Same-origin API proxy: the browser calls /api/* on this origin so the
      // httpOnly session cookie is first-party. This is the ONLY /api rewrite —
      // it serves `next dev` and Vercel alike, because Next.js rewrites are
      // resolved at build time (apiOrigin above reads the env then).
      //
      // Do NOT move this to vercel.json: that file is static JSON and Vercel
      // does not interpolate env vars in it, so a "${NEXT_PUBLIC_API_BASE_URL}"
      // destination is a literal string, silently shadows this rewrite, and
      // every /api/* call 404s in production while dev and `next start` stay
      // green. That outage took down sign-in once already.
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/:path*`,
      },
    ];
  },
  // Deep-link aliases resolve legacy labels to canonical live surfaces.
  async redirects() {
    return [
      { source: "/context-inbox", destination: "/ask", permanent: true },
      { source: "/inbox", destination: "/ask", permanent: true },
      { source: "/decision-log", destination: "/decisions", permanent: true },
      { source: "/team-board", destination: "/board", permanent: true },
      { source: "/org-graph", destination: "/graph", permanent: true },
      { source: "/data-routing", destination: "/integrations?tab=routing", permanent: true },
      { source: "/settings/data-routing", destination: "/integrations?tab=routing", permanent: true },
      // Workflows folded into Automations (transcript-extraction is now a mode there).
      { source: "/workflows", destination: "/automations", permanent: true },
    ];
  },
};

export default nextConfig;
