// Kept apart from lib/theme.ts (which uses React hooks) because the server-rendered layout imports it.
export const THEME_KEY = "lineage.theme"; // the same key as lib/theme.ts

/** Runs before the first paint (inlined in app/layout.tsx), so a remembered dark theme never flashes light. */
export const THEME_BOOT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}`;
