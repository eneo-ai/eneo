// @vitest-environment jsdom
import { cleanup, fireEvent, waitFor, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

const toast = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));

import { CopyableValue } from "./debug-section";

afterEach(cleanup);

it("says so when the clipboard refuses a technical value", async () => {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: () => Promise.reject(new DOMException("denied", "NotAllowedError")) },
    configurable: true
  });
  renderInApp(
    <dl>
      <CopyableValue label="Sessions-id" value="session-1" />
    </dl>
  );

  fireEvent.click(screen.getByRole("button", { name: "Kopiera Sessions-id" }));

  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(
      "Det gick inte att kopiera. Försök igen eller markera texten och kopiera den."
    )
  );
});
