import { browser } from "$app/environment";
import { replaceState } from "$app/navigation";
import { page } from "$app/state";
import { untrack } from "svelte";
import { SvelteURL } from "svelte/reactivity";

/**
 * A tab selection mirrored in `?tab=` so a tab can be linked to and survives
 * a reload, without adding history entries for every click.
 *
 * Call it while a component initialises. The tab is also kept in the history
 * entry's shallow state (`page.state.tab`): on Back/Forward SvelteKit restores
 * that state but gives `page.url` the URL the page first loaded with.
 */
export function urlTab<T extends string>(allowed: readonly T[], fallback: T) {
  const valid = (tab: string | null | undefined): T | undefined =>
    allowed.includes(tab as T) ? (tab as T) : undefined;
  const fromPage = () =>
    valid(page.state.tab) ?? valid(page.url.searchParams.get("tab")) ?? fallback;

  let value = $state<T>(untrack(fromPage));
  // History traversal and links to the same route keep this component, so follow them.
  $effect.pre(() => {
    const next = fromPage();
    untrack(() => (value = next));
  });

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
      replaceState(url, { ...page.state, tab: next });
    }
  };
}
