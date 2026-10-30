import { browser } from "$app/environment";
import { writable } from "svelte/store";
import { createContext } from "./context";

const [getThemeStore, setThemeStore] = createContext<ReturnType<typeof createThemeStore>>(
  "Store the user selected theme"
);

function initThemeStore() {
  const theme = createThemeStore();
  setThemeStore(theme);
  return theme;
}

export const availableThemes = ["system", "dark", "light"] as const;
export type Theme = (typeof availableThemes)[number];

function syncDarkClass(theme: Theme) {
  if (!browser) return;
  const isDark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", isDark);
}

function createThemeStore() {
  const themeKey = "theme";
  let initial: Theme = "system";

  if (browser) {
    try {
      initial = (window.localStorage.getItem(themeKey) as Theme) ?? "system";
    } catch (e) {
      console.error("No access to localStorage");
    }

    // Keep .dark class in sync when OS preference changes while using "system" theme
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (document.documentElement.dataset.theme === "system") {
        syncDarkClass("system");
      }
    });
  }

  const theme = writable<Theme>(initial);

  return {
    subscribe: theme.subscribe,
    set(newTheme: Theme) {
      if (browser) {
        document.documentElement.dataset.theme = newTheme;
        syncDarkClass(newTheme);
        window.localStorage.setItem(themeKey, newTheme);
      }
      theme.set(newTheme);
    }
  };
}

export { getThemeStore, initThemeStore };
