"use client";

import { useTheme } from "next-themes";
import { useEffect } from "react";
import { surfaceColors } from "@/theme/surface-colors";

/**
 * The browser's status bar and toolbar follow the Tema setting. The viewport
 * (app/layout.tsx) declares the surface colour per colour scheme, which is
 * right for "System"; an explicit Ljust or Mörkt sets both tags to that mode.
 * Renders nothing and holds no state, so it changes nothing above the page.
 */
export function ThemeColor() {
  const { theme } = useTheme();
  useEffect(() => {
    const colors = surfaceColors();
    for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
      const scheme = meta.media.includes("dark") ? "dark" : "light";
      meta.content = theme === "light" || theme === "dark" ? colors[theme] : colors[scheme];
    }
  }, [theme]);
  return null;
}
