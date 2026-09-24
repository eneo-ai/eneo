import { getContext, setContext } from "svelte";
import { get, type Writable } from "svelte/store";

const ctxKey = "content";

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
