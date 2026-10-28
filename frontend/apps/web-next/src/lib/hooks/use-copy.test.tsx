// @vitest-environment jsdom
import { act, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";

const toast = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

import { useCopy } from "./use-copy";

/** What Astryx's polite live region says now. */
const announced = () =>
  document.querySelector('[data-astryx-live-region="polite"]')?.textContent ?? "";

function clipboard(writeText: () => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

afterEach(() => {
  vi.clearAllMocks();
  document
    .querySelectorAll("[data-astryx-live-region]")
    .forEach((region) => (region.textContent = ""));
});

describe("useCopy", () => {
  it("announces a copy and shows it as copied", async () => {
    clipboard(() => Promise.resolve());
    const { result } = renderHookInApp(() => useCopy());

    await act(async () => expect(await result.current.copy("Hej")).toBe(true));

    await waitFor(() => expect(announced()).toBe("Kopierat till urklipp"));
    expect(result.current.isCopied).toBe(true);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("says once that the clipboard refused, and announces nothing", async () => {
    clipboard(() => Promise.reject(new DOMException("denied", "NotAllowedError")));
    const { result } = renderHookInApp(() => useCopy());

    await act(async () => expect(await result.current.copy("Hej")).toBe(false));

    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      "Det gick inte att kopiera. Försök igen eller markera texten och kopiera den."
    );
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(announced()).toBe("");
    expect(result.current.isCopied).toBe(false);
  });
});
