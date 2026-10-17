"use client";

import { chooseTheme, useTheme } from "@/lib/theme";

/** An on/off switch between the paper archive and the archive at night; the choice is remembered in this browser. */
export default function ThemeToggle() {
  const dark = useTheme() === "dark";
  return (
    <button className="theme-toggle" role="switch" aria-checked={dark} onClick={() => chooseTheme(dark ? "light" : "dark")}>
      <span className="theme-toggle-label">Dark</span>
      <span className="theme-toggle-track" aria-hidden="true"><span className="theme-toggle-thumb" /></span>
    </button>
  );
}
