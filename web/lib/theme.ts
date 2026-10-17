// The two palettes. The page's CSS variables (app/globals.css), the graph's styles (EvidenceGraph) and the
// canvas-drawn cards (lib/cards.ts) all take their colours from here; tests/theme.test.mjs keeps them in step.
// Dark is "the archive at night": slate paper, cream ink, and the stamp, pine, cyan and brass lifted to read on it.

import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

export type Palette = {
  paper: string; paperDeep: string; card: string; cardStale: string;
  ink: string; inkSoft: string; inkFaint: string; rule: string; edge: string; hatchLine: string;
  cyan: string; cyanWash: string; pine: string; pineWash: string; bleach: string;
  stamp: string; stampWash: string; brass: string; brassLight: string;
};

export const PALETTES: Record<Theme, Palette> = {
  light: {
    paper: "#eef1f3", paperDeep: "#e3e8ec", card: "#f8f9fa", cardStale: "#d5dae0",
    ink: "#18233a", inkSoft: "#4a5468", inkFaint: "#636c7c", rule: "#c9d0d8", edge: "#9aa3b2", hatchLine: "#7d8697",
    cyan: "#2f5d8c", cyanWash: "#dce6f0", pine: "#2a7354", pineWash: "#dcebe3", bleach: "#c9cfd6",
    stamp: "#c2273d", stampWash: "#f6dde1", brass: "#80621f", brassLight: "#f1d998",
  },
  dark: {
    paper: "#12161c", paperDeep: "#0d1015", card: "#1a1f27", cardStale: "#2c323b",
    ink: "#e8e2d2", inkSoft: "#b9b2a2", inkFaint: "#8f97a4", rule: "#2d3540", edge: "#5d6676", hatchLine: "#8f97a4",
    cyan: "#8ab4e0", cyanWash: "#1b2938", pine: "#6cc49a", pineWash: "#16281f", bleach: "#353c46",
    stamp: "#f07484", stampWash: "#3b1d24", brass: "#d8b062", brassLight: "#f1d998",
  },
};

export const THEME_KEY = "lineage.theme"; // also in lib/theme-boot.ts (tests/theme.test.mjs checks they agree)
const KEY = THEME_KEY;

/** The theme the page is showing: an explicit choice on <html data-theme>, else the system setting. */
export function currentTheme(): Theme {
  if (typeof document === "undefined") return "light";
  const set = document.documentElement.dataset.theme;
  if (set === "dark" || set === "light") return set;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Pin a theme (remembered in this browser), overriding the system setting. */
export function chooseTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem(KEY, t); } catch { /* private mode: it still applies for this visit */ }
  window.dispatchEvent(new Event("lineage-theme"));
}


/** The current theme, following both the visitor's choice and changes to the system setting. */
export function useTheme(): Theme {
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => {
    const update = () => setTheme(currentTheme());
    update();
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener("change", update);
    window.addEventListener("lineage-theme", update);
    return () => { mq?.removeEventListener("change", update); window.removeEventListener("lineage-theme", update); };
  }, []);
  return theme;
}
