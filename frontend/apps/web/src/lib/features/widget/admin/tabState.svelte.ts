import { browser } from "$app/environment";
import { replaceState } from "$app/navigation";
import { page } from "$app/state";
import { SvelteURL } from "svelte/reactivity";

/**
 * A tab selection mirrored in `?tab=` so a tab can be linked to and survives
 * a reload, without adding history entries for every click.
 */
export function urlTab<T extends string>(allowed: readonly T[], fallback: T) {
  const initial = page.url.searchParams.get("tab");
  let value = $state<T>(allowed.includes(initial as T) ? (initial as T) : fallback);

  return {
    get value() {
      return value;
    },
    set value(next: T) {
      value = next;
      if (!browser) return;
      const url = new SvelteURL(location.href);
      if (next === fallback) url.searchParams.delete("tab");
      else url.searchParams.set("tab", next);
      // Same page, only the query changes: nothing to resolve.
      // eslint-disable-next-line svelte/no-navigation-without-resolve
      replaceState(url, page.state);
    }
  };
}
