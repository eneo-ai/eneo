import { tick } from "svelte";

/**
 * Keeps keyboard focus in a control group whose pressed button may turn `disabled`
 * by what it does (a paginator's Next on the last page): a focused element that
 * becomes disabled drops focus to the body, or to the dialog around it.
 *
 * Create it when the button is activated, change the state, then hand off.
 */
export function focusHandoff(pressed: HTMLElement | null) {
  const held = pressed !== null && document.activeElement === pressed;
  return {
    /** Focuses `fallback` once the DOM shows `pressed` disabled, unless focus went elsewhere meanwhile. */
    async to(fallback: HTMLElement | null) {
      if (!held || !pressed || !fallback) return;
      await tick();
      if (!pressed.matches(":disabled")) return;
      const active = document.activeElement;
      if (active !== pressed && active !== document.body && !active?.contains(pressed)) return;
      fallback.focus();
    }
  };
}
