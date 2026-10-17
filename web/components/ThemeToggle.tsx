"use client";

import { chooseTheme, useTheme } from "@/lib/theme";

/** Switches between the paper archive and the archive at night; the choice is remembered in this browser. */
export default function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button className="theme-toggle" onClick={() => chooseTheme(next)} aria-label={`Switch to ${next} mode`}>
      {next === "dark" ? "Dark mode" : "Light mode"}
    </button>
  );
}
