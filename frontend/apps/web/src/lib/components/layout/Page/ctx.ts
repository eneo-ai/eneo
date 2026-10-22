import { getContext, setContext } from "svelte";
import { get, type Writable } from "svelte/store";
import { browser } from "$app/environment";
import { replaceState } from "$app/navigation";
import { page } from "$app/state";

const ctxKey = "content";

/** Shows `tab` and records it in the URL, so a reload or a shared link opens the same tab. */
export function selectPageTab(tabs: Writable<string>, tab: string): void {
  tabs.set(tab);
  if (!browser) return;
  // replaceState never updates page.url: the address bar also holds earlier shallow
  // changes, such as a selected content directory, which a tab switch must keep.
  const url = new URL(location.href);
  url.searchParams.set("tab", tab);
  // Reset to page 1 when switching tabs to avoid empty results
  url.searchParams.delete("page");
  // replaceState updates the URL without a SvelteKit navigation, so no load function re-runs.
  // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with mutated query params
  replaceState(url, { ...page.state, tab });
}

export type ContentTabs = {
  value: Writable<string>;
  /** Selects the first registered tab when nothing is selected yet. */
  registerTab: (tab: string) => void;
};

export function createContentTabs(value: Writable<string>): ContentTabs {
  const ctx: ContentTabs = {
    value,
    registerTab(tab) {
      if (!get(value)) value.set(tab);
    }
  };
  setContext<ContentTabs>(ctxKey, ctx);
  return ctx;
}

export function getContentTabs() {
  return getContext<ContentTabs>(ctxKey);
}

export type ValueState = Writable<string>;
