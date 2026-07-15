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
  assert.match(html, /<summary role="button" aria-label="Navigation menu" aria-controls="mobile-navigation" aria-expanded="false">/);
  assert.match(html, /mobileMenuTrigger\.setAttribute\('aria-expanded', String\(mobileMenu\.open\)\)/);
  assert.match(html, /mobileMenu\.removeAttribute\('open'\)/);
  assert.equal((html.match(/>Book a Call<\/a>/g) ?? []).length, 3);
  assert.equal((html.match(/>Try a Demo<\/a>/g) ?? []).length, 3);
  assert.equal((html.match(new RegExp(`<a href="${calendarUrl}" target="_blank" rel="noopener noreferrer" aria-label="Book a Call \\(opens in a new tab\\)" class="btn btn-secondary btn-lg">Book a Call<\\/a>`, "g")) ?? []).length, 2);
  assert.equal((html.match(/<a href="\/demo" class="btn btn-primary(?: btn-lg)?">Try a Demo<\/a>/g) ?? []).length, 3);
  assert.doesNotMatch(html, /Share your workflow|Get a demo|See how Sheldon works/);
  assert.doesNotMatch(html, /<section class="positioning">/);
  assert.match(css, /\.landing-saas \.hero\s*{[^}]*min-height: auto !important;/s);
  assert.match(css, /\.landing-saas \.nav-mobile-menu\[open\]::before\s*,\s*\.landing-university \.nav-mobile-menu\[open\]::before\s*{/);
  assert.match(css, /@media \(max-width: 980px\)\s*{[\s\S]*?\.nav-mobile-menu\s*{\s*display: block;/);
  assert.match(html, /landing-eleven\.css\?v=20260715-saas-loop/);
  assert.match(universityHtml, /landing-eleven\.css\?v=20260714-ui-audit/);
  assert.doesNotMatch(html, /Explore live workflow/);
  assert.match(html, /matchMedia\('\(prefers-reduced-motion: reduce\)'\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.prose p strong\s*{[^}]*color: var\(--el-ink\) !important;/s);
  assert.match(css, /\.out-cell p\s*{[^}]*color: var\(--el-body\) !important;/s);
});

test("homepage preserves the approved positioning and section content", () => {
  assert.match(
    html,
    /<h1>Run your company on autopilot\.<\/h1>\s*<p class="hero-positioning">Turn company context into workflows that move\.<\/p>\s*<p class="hero-sub">Sheldon absorbs your company's context,[\s\S]*?learning from every outcome\.<\/p>/,
  );
  assert.match(
    html,
    /<p class="hero-micro">Built for fast-moving teams that want to scale execution without losing context\.<\/p>\s*<div class="hero-actions">/,
  );
  assert.match(html, /<h2 id="loop-title">Sheldon acts like an AI-native operating system that runs your company\.<\/h2>/);
  assert.equal((html.match(/<article class="loop-node /g) ?? []).length, 4);
  assert.equal((html.match(/<article class="saas-workflow /g) ?? []).length, 6);
  assert.equal((html.match(/<span aria-hidden="true">→<\/span>/g) ?? []).length, 24);
  assert.equal((html.match(/<div class="feat-card /g) ?? []).length, 6);
  assert.match(html, /One brain to remember\. A team of agents to execute\./);
  assert.match(html, /Got work\?<br>Consider it done\.<span class="final-signoff">Signed, Sheldon\.<\/span>/);
  assert.doesNotMatch(html, /We respond within 24 hours\./);
  assert.equal((html.match(/Run your company on autopilot\.<\/p>|Run your company on autopilot\.<\/span>/g) ?? []).length, 2);
});

test("homepage keeps loop, workflow, feature, and focus layouts responsive", () => {
  assert.match(html, /\.loop-orbit\s*{[\s\S]*?grid-template-areas:[\s\S]*?"learn hub decide"[\s\S]*?"\. act \.":?;/);
  assert.equal((html.match(/class="loop-arrow /g) ?? []).length, 4);
  assert.match(html, /\.landing-saas a:focus-visible,\s*\.landing-saas summary:focus-visible\s*{/);
  assert.match(html, /@media \(max-width: 980px\)[\s\S]*?\.loop-orbit\s*{\s*display: flex;\s*flex-direction: column;/);
  assert.match(html, /\.loop-hub::after\s*{[\s\S]*?Back to ingest/);
  assert.match(html, /@media \(max-width: 980px\)[\s\S]*?\.saas-workflow\s*{\s*grid-template-columns: 36px/);
  assert.match(html, /@media \(max-width: 560px\)[\s\S]*?\.landing-saas \.feat-grid\s*{\s*grid-template-columns: 1fr;/);
  assert.match(html, /@media \(max-width: 560px\)[\s\S]*?\.saas-workflow\s*{\s*grid-template-columns: 32px 1fr;/);
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
