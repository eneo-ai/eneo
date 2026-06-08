import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import ExpandableErrorRow from "./ExpandableErrorRow.svelte";

describe("ExpandableErrorRow", () => {
  it("shows label and failed status but hides the message until expanded", async () => {
    render(ExpandableErrorRow, {
      label: "document.pdf",
      message: "Unsupported file type"
    });

    await expect.element(page.getByText("document.pdf", { exact: true })).toBeVisible();
    await expect.element(page.getByText(m.failed(), { exact: true })).toBeVisible();
    await expect
      .element(page.getByText("Unsupported file type", { exact: true }))
      .not.toBeInTheDocument();
  });

  it("reveals the message and toggles aria-expanded on click", async () => {
    render(ExpandableErrorRow, {
      label: "document.pdf",
      message: "Unsupported file type"
    });

    const row = page.getByRole("button");
    await expect.element(row).toHaveAttribute("aria-expanded", "false");

    await row.click();
    await expect.element(page.getByText("Unsupported file type", { exact: true })).toBeVisible();
    await expect.element(row).toHaveAttribute("aria-expanded", "true");

    await row.click();
    await expect
      .element(page.getByText("Unsupported file type", { exact: true }))
      .not.toBeInTheDocument();
    await expect.element(row).toHaveAttribute("aria-expanded", "false");
  });
});
