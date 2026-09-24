import { vi } from "vitest";
import { EneoWidgetElement } from "./element";

/** Answers every element's settings request with `settings`; undefined means no settings. */
export function stubSettings(settings: unknown = undefined) {
  return vi
    .spyOn(EneoWidgetElement.prototype as never, "fetchSettings" as never)
    .mockImplementation((() => Promise.resolve(settings)) as never);
}

/** Lets the settings requests already in flight resolve. */
export function flushSettings(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}
