import { EneoWidgetElement } from "./element";

/** Attributes copied from the script tag's `data-*` onto the element. */
const SCRIPT_ATTRIBUTES = [
  "widget-id",
  "base-url",
  "lang",
  "position",
  "color-scheme",
  "auto-open",
  "launcher",
  "label",
  "frame-title",
  "prefetch",
  "preview"
] as const;

/** The origin of the script tag is where the embed page and API live. */
export function resolveOrigin(script: HTMLScriptElement | null, fallback: string): string {
  if (!script?.src) return fallback;
  try {
    return new URL(script.src, location.href).origin;
  } catch {
    return fallback;
  }
}

/**
 * `<script async src="…/widget/v1/eneo.js" data-widget-id="wgt_…">` mounts
 * one element on the body. SPA hosts skip the data attribute and render
 * `<eneo-widget>` themselves.
 */
export function mountFromScript(script: HTMLScriptElement, doc: Document = document): void {
  const id = script.dataset.widgetId;
  if (!id) return;
  const mount = () => {
    // Compared as attribute values, not interpolated into a selector: an id
    // with a quote or bracket must not throw inside the host page.
    const mounted = Array.from(doc.querySelectorAll("eneo-widget")).some(
      (existing) => existing.getAttribute("widget-id") === id
    );
    if (mounted) return;
    const element = doc.createElement("eneo-widget") as EneoWidgetElement;
    for (const name of SCRIPT_ATTRIBUTES) {
      const value = script.getAttribute(`data-${name}`);
      if (value !== null) element.setAttribute(name, value);
    }
    doc.body.appendChild(element);
    if (element.getAttribute("prefetch") === "true") element.prefetch();
  };
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", mount, { once: true });
  else mount();
}
