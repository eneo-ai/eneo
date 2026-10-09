import { vi } from "vitest";
import { EneoWidgetElement } from "./element";

/** The element's protected seams, as tests replace them. */
interface Seams {
  fetchSettings(url: string): Promise<unknown>;
  post(target: Window | null, data: Record<string, unknown>): void;
}

/** Spies on a protected seam without losing its signature. */
export function spyOnSeam<K extends keyof Seams>(target: EneoWidgetElement, name: K) {
  return vi.spyOn(target as unknown as Seams, name);
}

/** Answers every element's settings request with `settings`; undefined means no settings. */
export function stubSettings(settings: unknown = undefined) {
  return spyOnSeam(EneoWidgetElement.prototype, "fetchSettings").mockImplementation(() =>
    Promise.resolve(settings)
  );
}

/** Lets the settings requests already in flight resolve. */
export function flushSettings(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}
