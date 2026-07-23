import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

function envValue(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value || undefined;
}

export function GET() {
  return NextResponse.json(
    {
      status: "ok",
      service: "osai-web",
      environment: envValue("VERCEL_ENV") ?? envValue("OSAI_ENV") ?? "local",
      build_sha:
        envValue("VERCEL_GIT_COMMIT_SHA") ??
        envValue("OSAI_BUILD_SHA") ??
        "unknown",
    },
    {
      headers: {
        "Cache-Control": "no-store",
      },
    }
  );
}
