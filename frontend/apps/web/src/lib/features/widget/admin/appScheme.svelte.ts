import { currentAppScheme } from "./appScheme";

/**
 * `currentAppScheme()` read as reactive state: follows the theme switch in
 * the header and the system setting while the page is open, so previews and
 * the in-app test change with the admin's own view instead of staying on
 * what was true at mount.
 */
export function watchAppScheme(): { readonly current: "light" | "dark" } {
  let current = $state<"light" | "dark">(currentAppScheme());

  $effect(() => {
    if (typeof document === "undefined") return;
    const update = () => (current = currentAppScheme());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"]
    });
    const query =
      typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)") : null;
    query?.addEventListener("change", update);
    return () => {
      observer.disconnect();
      query?.removeEventListener("change", update);
    };
  });

  return {
    get current() {
      return current;
    }
  };
}
