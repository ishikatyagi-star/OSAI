import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { brandText } from "../lib/utils.ts";

const html = await readFile(new URL("../public/saas.html", import.meta.url), "utf8");
const universityHtml = await readFile(new URL("../public/osai.html", import.meta.url), "utf8");
const css = await readFile(new URL("../public/landing-eleven.css", import.meta.url), "utf8");
const root = fileURLToPath(new URL("..", import.meta.url));

async function frontendSourceFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    const target = path.join(dir, entry.name);
    return entry.isDirectory() ? frontendSourceFiles(target) : [target];
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
  assert.match(html, /See how Sheldon works/);
  assert.doesNotMatch(html, /Explore live workflow/);
  assert.match(html, /matchMedia\('\(prefers-reduced-motion: reduce\)'\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.prose p strong\s*{[^}]*color: var\(--el-ink\) !important;/s);
  assert.match(css, /\.out-cell p\s*{[^}]*color: var\(--el-body\) !important;/s);
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
