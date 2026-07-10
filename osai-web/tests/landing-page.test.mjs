import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const html = await readFile(new URL("../public/saas.html", import.meta.url), "utf8");
const css = await readFile(new URL("../public/landing-eleven.css", import.meta.url), "utf8");

test("homepage keeps its audit fixes", () => {
  assert.equal((html.match(/<main\b/g) ?? []).length, 1);
  assert.equal((html.match(/<\/main>/g) ?? []).length, 1);
  assert.match(html, /<details class="nav-mobile-menu">/);
  assert.match(html, /mobileMenu\.removeAttribute\('open'\)/);
  assert.match(html, /See how OSAI works/);
  assert.doesNotMatch(html, /Explore live workflow/);
  assert.match(html, /matchMedia\('\(prefers-reduced-motion: reduce\)'\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.prose p strong\s*{[^}]*color: var\(--el-ink\) !important;/s);
  assert.match(css, /\.out-cell p\s*{[^}]*color: var\(--el-body\) !important;/s);
});
