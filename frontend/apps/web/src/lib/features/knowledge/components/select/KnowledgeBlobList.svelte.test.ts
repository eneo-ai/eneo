import type { InfoBlob } from "@intric/intric-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import KnowledgeBlobList from "./KnowledgeBlobList.svelte";

const blobs = Array.from(
  { length: 11 },
  (_, index) =>
    ({
      id: `blob-${index + 1}`,
      metadata: { title: `Document ${index + 1}` }
    }) as InfoBlob
);

describe("KnowledgeBlobList", () => {
  it("moves between pages and exposes localized pagination labels", async () => {
    render(KnowledgeBlobList, {
      blobs,
      emptyMessage: "No documents"
    });

    await expect.element(page.getByText("Document 1", { exact: true })).toBeVisible();
    await expect.element(page.getByText("Document 11", { exact: true })).not.toBeInTheDocument();

    const next = page.getByRole("button", { name: m.aria_go_to_next_page() });
    await expect.element(next).toBeVisible();
    await next.click();

    await expect.element(page.getByText("Document 11", { exact: true })).toBeVisible();
    await expect.element(page.getByText("Document 1", { exact: true })).not.toBeInTheDocument();
    await expect
      .element(page.getByRole("button", { name: m.aria_go_to_previous_page() }))
      .toBeVisible();
  });
});
