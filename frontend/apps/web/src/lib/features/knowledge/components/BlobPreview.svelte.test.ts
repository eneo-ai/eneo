import type { InfoBlob } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as m from "$lib/paraglide/messages";

const generateOriginalSignedUrl = vi.hoisted(() => vi.fn());
const getBlob = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    infoBlobs: { get: getBlob, generateOriginalSignedUrl }
  })
}));

vi.mock("$lib/components/toast", () => ({
  toast: { error: toastError }
}));

import BlobPreview from "./BlobPreview.svelte";

const blob = (original_available?: boolean): InfoBlob =>
  ({
    id: "blob-1",
    metadata: { title: "Source document" },
    text: "Extracted text",
    original_available
  }) as InfoBlob;

describe("BlobPreview", () => {
  beforeEach(() => {
    getBlob.mockReset();
    generateOriginalSignedUrl.mockReset();
    toastError.mockReset();
    getBlob.mockResolvedValue({ text: "Extracted text" });
    generateOriginalSignedUrl.mockResolvedValue({
      url: "https://eneo.example/api/v1/info-blobs/blob-1/original/download/?token=signed"
    });
  });

  it("shows original download separately and opens its signed URL", async () => {
    const initialUrl = window.location.href;
    generateOriginalSignedUrl.mockResolvedValue({
      url: `${window.location.origin}${window.location.pathname}#blob-1-original-download`
    });

    try {
      render(BlobPreview, { blob: blob(true) });

      await page.getByRole("button", { name: /Source document/ }).click();
      const download = page.getByRole("button", { name: m.download_original() });
      await expect.element(download).toBeVisible();
      await download.click();

      await vi.waitFor(() =>
        expect(generateOriginalSignedUrl).toHaveBeenCalledWith({
          infoBlobId: "blob-1",
          contentDisposition: "attachment"
        })
      );
    } finally {
      history.replaceState(null, "", initialUrl);
    }
  });

  it("does not offer an original download when no original is available", async () => {
    render(BlobPreview, { blob: blob(false) });

    await page.getByRole("button", { name: /Source document/ }).click();
    await expect
      .element(page.getByRole("button", { name: m.download_original() }))
      .not.toBeInTheDocument();
  });

  it("adopts original availability from the lazy detail response", async () => {
    getBlob.mockResolvedValue({ text: "Extracted text", original_available: true });

    render(BlobPreview, { blob: blob() });

    await page.getByRole("button", { name: /Source document/ }).click();
    await expect.element(page.getByRole("button", { name: m.download_original() })).toBeVisible();
    expect(getBlob).toHaveBeenCalledWith(expect.objectContaining({ id: "blob-1" }));
  });

  it("reports a failed link request and restores the download action", async () => {
    generateOriginalSignedUrl.mockRejectedValue(new Error("link failed"));
    render(BlobPreview, { blob: blob(true) });

    await page.getByRole("button", { name: /Source document/ }).click();
    const download = page.getByRole("button", { name: m.download_original() });
    await download.click();

    await vi.waitFor(() => expect(toastError).toHaveBeenCalledWith(m.error_downloading_original()));
    await expect.element(download).toBeEnabled();
  });
});
