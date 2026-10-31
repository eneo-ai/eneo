// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { lazyRouteComponent } from "@tanstack/react-router";
import { Suspense, type FunctionComponent } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RootErrorBoundary } from "@/components/shell/root-error-boundary";
import { installChunkRecovery } from "./chunk-recovery";

const reload = vi.fn();
let removeRecovery: () => void;

beforeEach(() => {
  reload.mockClear();
  vi.stubGlobal("window", Object.create(window, { location: { value: { reload } } }));
  vi.spyOn(console, "error").mockImplementation(() => {});
  removeRecovery = installChunkRecovery();
});

afterEach(() => {
  removeRecovery();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function preloadError(error: Error) {
  const event = Object.assign(new Event("vite:preloadError", { cancelable: true }), {
    payload: error
  });
  window.dispatchEvent(event);
  return event;
}

it("shows the import failure when the document stays open instead of suspending forever", async () => {
  const Missing = lazyRouteComponent(async (): Promise<{ default: FunctionComponent }> => {
    throw new TypeError("Failed to fetch dynamically imported module: https://app.test/old.js");
  });
  await Missing.preload?.();

  render(
    <RootErrorBoundary>
      <Suspense fallback={<p>Pending route</p>}>
        <Missing />
      </Suspense>
    </RootErrorBoundary>
  );

  expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeTruthy();
  expect(screen.queryByText("Pending route")).toBeNull();
});

it("does not start another document reload for a different missing route", async () => {
  for (const name of ["first", "second"]) {
    const Missing = lazyRouteComponent(async (): Promise<{ default: FunctionComponent }> => {
      const error = new TypeError(
        `Failed to fetch dynamically imported module: https://app.test/${name}.js`
      );
      preloadError(error);
      throw error;
    });
    await Missing.preload?.();
    const view = render(
      <RootErrorBoundary>
        <Suspense fallback={<p>Pending route</p>}>
          <Missing />
        </Suspense>
      </RootErrorBoundary>
    );
    await screen.findByRole("heading", { name: "Something went wrong" });
    view.unmount();
  }

  expect(reload).toHaveBeenCalledOnce();
});

it("preserves the rejection and shares the budget with the next document", () => {
  const error = new TypeError("Importing a module script failed");
  const event = preloadError(error);
  expect(event.defaultPrevented).toBe(false);
  expect(event.payload).toBe(error);
  expect(reload).toHaveBeenCalledOnce();

  removeRecovery();
  removeRecovery = installChunkRecovery();
  preloadError(new Error("Unable to preload CSS for /assets/old.css"));
  expect(reload).toHaveBeenCalledOnce();
});

it.each(["getItem", "setItem"] as const)(
  "leaves the original failure visible without reloading when storage %s fails",
  (method) => {
    vi.spyOn(Storage.prototype, method).mockImplementation(() => {
      throw new DOMException("Storage unavailable", "SecurityError");
    });
    const event = preloadError(new TypeError("Importing a module script failed"));
    expect(event.defaultPrevented).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  }
);
