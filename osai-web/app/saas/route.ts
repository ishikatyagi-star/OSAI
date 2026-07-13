import { NextResponse } from "next/server";
import { readFileSync } from "fs";
import { join } from "path";

export const dynamic = "force-static";

export function GET(request: Request) {
  try {
    const html = readFileSync(
      join(process.cwd(), "public", "saas.html"),
      "utf-8"
    );
    return new NextResponse(html, {
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  } catch {
    // Fallback if file not found
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
}
