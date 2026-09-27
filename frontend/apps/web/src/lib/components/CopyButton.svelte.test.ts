import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "$lib/components/toast";
import { m } from "$lib/paraglide/messages";
import CopyButton from "./CopyButton.svelte";

vi.mock("$lib/components/toast", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

afterEach(() => {
  vi.restoreAllMocks();
  vi.mocked(toast.error).mockReset();
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
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    render(CopyButton, { text: "secret", showLabel: true, label: "Copy" });

    await page.getByRole("button", { name: "Copy" }).click();

    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith(m.could_not_copy()));
    expect(page.getByText(m.copied()).elements()).toHaveLength(0);
  });
});
