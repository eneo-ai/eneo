// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
import { createTranslator } from "use-intl";
import { toast as sonner } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Toaster } from "@/components/ui/sonner";
import sv from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import { EneoApiError } from "./errors";
import { toastApiError } from "./toast";

const t = createTranslator({ locale: "sv", messages: sv }) as unknown as (key: string) => string;

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  renderInApp(<Toaster theme="light" />);
});

afterEach(async () => {
  sonner.dismiss();
  await act(() => vi.advanceTimersByTimeAsync(300));
  cleanup();
  vi.useRealTimers();
});

describe("toastApiError", () => {
  it("quotes the error id and trace id under the user's language labels", async () => {
    toastApiError(
      new EneoApiError("An unexpected error occurred.", {
        status: 500,
        errorId: "8bc91e0a",
        traceId: "trace-123"
      }),
      t
    );
    await act(() => vi.advanceTimersByTimeAsync(300));

    expect(screen.getByText("Fel-ID: 8bc91e0a · Spårnings-ID: trace-123")).toBeTruthy();
    // No hard-coded English label in the Swedish UI.
    expect(screen.queryByText(/Trace/)).toBeNull();
  });

  it("says a feature's own words, what failed first, and keeps the references after them", async () => {
    const error = new EneoApiError("Gone.", { status: 404, traceId: "trace-123" });
    toastApiError(error, t, { message: "Körningen finns inte längre." });
    toastApiError(error, t, {
      title: "Det gick inte att avbryta körningen",
      message: "Körningen finns inte längre."
    });
    await act(() => vi.advanceTimersByTimeAsync(300));

    expect(screen.getByText("Körningen finns inte längre.")).toBeTruthy();
    expect(screen.getByText("Spårnings-ID: trace-123")).toBeTruthy();
    expect(screen.getByText("Det gick inte att avbryta körningen")).toBeTruthy();
    expect(screen.getByText("Körningen finns inte längre. · Spårnings-ID: trace-123")).toBeTruthy();
  });
});
