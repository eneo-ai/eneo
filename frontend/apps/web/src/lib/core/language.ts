import { browser } from "$app/environment";
import { writable } from "svelte/store";
import { createContext } from "./context";
import { getLocale, setLocale, type Locale } from "$lib/paraglide/runtime";

const [getLanguageStore, setLanguageStore] = createContext<ReturnType<typeof createLanguageStore>>(
  "Store the user selected language"
);

function initLanguageStore() {
  const language = createLanguageStore();
  setLanguageStore(language);
  return language;
}

export const availableLanguages = ["sv", "en"] as const;
export type Language = (typeof availableLanguages)[number];

function createLanguageStore() {
  const languageKey = "language";
  let initial: Language = getLocale() as Language;

  if (browser) {
    try {
      // Try to get from localStorage first
      const stored = window.localStorage.getItem(languageKey) as Language;
      if (stored && availableLanguages.includes(stored)) {
        initial = stored;
      }
    } catch (e) {
      console.error("No access to localStorage");
    }
  }

  const language = writable<Language>(initial);

  return {
    subscribe: language.subscribe,
    set(newLanguage: Language) {
      if (browser) {
        window.localStorage.setItem(languageKey, newLanguage);
        // Use Paraglide's setLocale which will handle the page reload
        setLocale(newLanguage as Locale);
      }
      language.set(newLanguage);
    }
  };
}

export { getLanguageStore, initLanguageStore };