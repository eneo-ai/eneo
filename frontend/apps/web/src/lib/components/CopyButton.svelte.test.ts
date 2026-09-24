import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toastError } from "$lib/core/errors";
import { m } from "$lib/paraglide/messages";
import CopyButton from "./CopyButton.svelte";

vi.mock("$lib/core/errors", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/core/errors")>()),
  toastError: vi.fn()
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.mocked(toastError).mockReset();
});

describe("CopyButton", () => {
  it("copies the text read at click time and announces it", async () => {
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    let value = "first";
    render(CopyButton, { text: () => value, label: "Copy key" });

    value = "second";
    await page.getByRole("button", { name: "Copy key" }).click();

    expect(writeText).toHaveBeenCalledWith("second");
    await expect.element(page.getByText(m.copied())).toBeInTheDocument();
  });

  it("reports a failed copy instead of claiming success", async () => {
    const error = new Error("denied");
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(error);
    render(CopyButton, { text: "secret", showLabel: true, label: "Copy" });

    await page.getByRole("button", { name: "Copy" }).click();

    await vi.waitFor(() => expect(toastError).toHaveBeenCalledWith(error, m.could_not_copy()));
    expect(page.getByText(m.copied()).elements()).toHaveLength(0);
  });
});
