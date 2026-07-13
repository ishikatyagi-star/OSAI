import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { brandText } from "../lib/utils.ts";

const html = await readFile(new URL("../public/saas.html", import.meta.url), "utf8");
const universityHtml = await readFile(new URL("../public/osai.html", import.meta.url), "utf8");
const css = await readFile(new URL("../public/landing-eleven.css", import.meta.url), "utf8");
const nextConfig = await readFile(new URL("../next.config.ts", import.meta.url), "utf8");
const landingRoute = await readFile(new URL("../app/landing/route.ts", import.meta.url), "utf8");
const root = fileURLToPath(new URL("..", import.meta.url));
const calendarUrl = "https://calendar.google.com/calendar/u/0/appointments/schedules/AcZssZ3qwSMjKMhXKW7-NFO0ZqHthdvO6MUio_sAy1UUk1qHU4jbXD6AZhcx5zOzlLeyxFFBdP923DBN";
const sourceExtensions = new Set([".css", ".html", ".js", ".jsx", ".json", ".mjs", ".svg", ".ts", ".tsx"]);

async function frontendSourceFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    const target = path.join(dir, entry.name);
    return entry.isDirectory()
      ? frontendSourceFiles(target)
      : sourceExtensions.has(path.extname(entry.name)) ? [target] : [];
  }));
  return files.flat();
}

function withoutDataUris(source) {
  return source.replace(/data:[^"']+/g, "");
}

function visibleText(source) {
  return withoutDataUris(source).replace(/<[^>]+>/g, "");
}

test("homepage keeps its audit fixes", () => {
  assert.equal((html.match(/<main\b/g) ?? []).length, 1);
  assert.equal((html.match(/<\/main>/g) ?? []).length, 1);
  assert.match(html, /<details class="nav-mobile-menu">/);
  assert.match(html, /mobileMenu\.removeAttribute\('open'\)/);
  assert.equal((html.match(/>Book a Call<\/a>/g) ?? []).length, 3);
  assert.equal((html.match(/>Try a Demo<\/a>/g) ?? []).length, 3);
  assert.equal((html.match(new RegExp(`<a href="${calendarUrl}" target="_blank" rel="noopener noreferrer" aria-label="Book a Call \\(opens in a new tab\\)" class="btn btn-secondary btn-lg">Book a Call<\\/a>`, "g")) ?? []).length, 2);
  assert.equal((html.match(/<a href="\/demo" class="btn btn-primary(?: btn-lg)?">Try a Demo<\/a>/g) ?? []).length, 3);
  assert.doesNotMatch(html, /Share your workflow|Get a demo|See how Sheldon works/);
  assert.doesNotMatch(html, /<section class="positioning">/);
  assert.match(css, /\.landing-saas \.hero\s*{[^}]*min-height: auto !important;/s);
  assert.match(css, /\.landing-saas \.nav-mobile-menu\[open\]::before\s*,\s*\.landing-university \.nav-mobile-menu\[open\]::before\s*{/);
  assert.match(html, /landing-eleven\.css\?v=20260714-ui-audit/);
  assert.match(universityHtml, /landing-eleven\.css\?v=20260714-ui-audit/);
  assert.doesNotMatch(html, /Explore live workflow/);
  assert.match(html, /matchMedia\('\(prefers-reduced-motion: reduce\)'\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.prose p strong\s*{[^}]*color: var\(--el-ink\) !important;/s);
  assert.match(css, /\.out-cell p\s*{[^}]*color: var\(--el-body\) !important;/s);
});

test("website contains no share-workflow CTA", async () => {
  const publicFiles = await frontendSourceFiles(path.join(root, "public"));
  for (const file of publicFiles.filter((file) => path.extname(file) === ".html")) {
    assert.doesNotMatch(await readFile(file, "utf8"), /Share your workflow/i, file);
  }
});

test("root landing route does not shadow app routes", () => {
  assert.match(nextConfig, /source:\s*["']\/["'],\s*destination:\s*["']\/landing["']/);
  assert.match(landingRoute, /public.*saas\.html/s);
});

test("marketing pages expose only the Sheldon brand", () => {
  for (const source of [html, withoutDataUris(universityHtml)]) {
    const text = visibleText(source);
    assert.match(text, /\bSheldon\b/);
    assert.doesNotMatch(source, new RegExp(["Sheldon", "AI"].join(" ")));
    assert.doesNotMatch(text, /\bOSAI\b/);
    assert.doesNotMatch(source, /—|&mdash;|&#8212;|&#x2014;|\\u2014/);
  }
});

test("frontend source contains no em dash and no unapproved visible OSAI copy", async () => {
  const files = (
    await Promise.all(["app", "components", "lib", "public"].map((dir) => frontendSourceFiles(path.join(root, dir))))
  ).flat();

  for (const file of files) {
    let source = withoutDataUris(await readFile(file, "utf8"));
    source = source
      .replaceAll("OSAI_OPENUI_PROMPT", "")
      .replaceAll("NEXT_PUBLIC_OSAI_DEMO", "");
    assert.doesNotMatch(source, /—|&mdash;|&#8212;|&#x2014;|\\u2014/, file);
    assert.doesNotMatch(source, /\bOSAI\b/, file);
  }
});

test("legacy backend copy is normalized only when displayed", () => {
  assert.equal(brandText("OSAI Demo Org"), "Sheldon Demo Org");
  assert.equal(
    brandText("Set OSAI_NOTION_API_TOKEN to enable Notion sync."),
    "Set the required integration setting to enable Notion sync.",
  );
  assert.equal(brandText("osai — &mdash; &#8212; &#x2014; \\u2014"), "Sheldon - - - - -");
});
