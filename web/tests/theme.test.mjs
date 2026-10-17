import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PALETTES } from "../lib/theme.ts";

// WCAG relative luminance and contrast ratio
const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

test("both themes define the same colours", () => {
  assert.deepEqual(Object.keys(PALETTES.dark).sort(), Object.keys(PALETTES.light).sort());
});

test("text and meaning colours stay readable on the page and on cards in both themes", () => {
  for (const name of ["light", "dark"]) {
    const P = PALETTES[name];
    for (const fg of ["ink", "inkSoft", "inkFaint", "stamp", "cyan", "pine", "brass"]) {
      for (const bg of ["paper", "card"]) {
        const c = contrast(P[fg], P[bg]);
        assert.ok(c >= 4.5, `${name}: ${fg} on ${bg} is ${c.toFixed(2)}:1`);
      }
    }
  }
});

test("the stylesheet's dark tokens are the palette's dark colours", () => {
  const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
  const block = css.match(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/);
  assert.ok(block, "no :root[data-theme=\"dark\"] block");
  const kebab = (k) => k.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
  let checked = 0;
  for (const [k, v] of Object.entries(PALETTES.dark)) {
    const m = block[1].match(new RegExp(`--${kebab(k)}:\\s*(#[0-9a-fA-F]{6})`));
    if (m) { assert.equal(m[1].toLowerCase(), v.toLowerCase(), `--${kebab(k)}`); checked++; }
  }
  assert.ok(checked >= 12, `only ${checked} tokens matched`);
});

test("the pre-paint script reads the key the theme switch writes", async () => {
  const { THEME_KEY } = await import("../lib/theme.ts");
  const boot = await import("../lib/theme-boot.ts");
  assert.equal(boot.THEME_KEY, THEME_KEY);
  assert.ok(boot.THEME_BOOT.includes(`"${THEME_KEY}"`));
});

test("following the system and choosing dark give the same colours", () => {
  const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const viaSystem = css.match(/:root:not\(\[data-theme="light"\]\)\s*\{([^}]*)\}/)[1];
  const chosen = css.match(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/)[1];
  assert.equal(norm(viaSystem), norm(chosen));
});
