import type { Group, InfoBlob } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import BlobUpload from "./BlobUpload.svelte";

// BlobUpload reads the app, job-manager and client contexts, which are only
// provided by the app shell, so stub them with the smallest shape it touches.
const mocks = vi.hoisted(() => {
  const store = <T>(initial: T) => {
    let value = initial;
    const subscribers = new Set<(value: T) => void>();
    return {
      subscribe(run: (value: T) => void) {
        subscribers.add(run);
        run(value);
        return () => {
          subscribers.delete(run);
        };
      },
      set(next: T) {
        value = next;
        subscribers.forEach((run) => run(value));
      },
      get value() {
        return value;
      }
    };
  };
  return {
    queueUploads: vi.fn(),
    getSummary: vi.fn(),
    showHeader: store(false),
    showJobManagerPanel: store(false),
    user: { quota_limit: null as number | null, quota_used: 0 },
    limits: {
      info_blobs: {
        formats: [
          { mimetype: "application/pdf", extensions: [".pdf"], size: 1024, vision: false },
          { mimetype: "text/plain", extensions: [".txt"], size: 1024, vision: false }
        ]
      },
      attachments: { formats: [] }
    }
  };
});

vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    limits: mocks.limits,
    user: mocks.user,
    state: { showHeader: mocks.showHeader }
  })
}));
vi.mock("$lib/features/jobs/JobManager", () => ({
  getJobManager: () => ({
    queueUploads: mocks.queueUploads,
    state: { showJobManagerPanel: mocks.showJobManagerPanel }
  })
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ usage: { storage: { getSummary: mocks.getSummary } } })
}));

const collection = { id: "collection-1", name: "Policies" } as Group;
const existingBlob = { id: "blob-1", metadata: { title: "existing.pdf" } } as InfoBlob;

function selectFiles(files: File[]) {
  const input = document.querySelector("input[type=file]") as HTMLInputElement;
  const dataTransfer = new DataTransfer();
  for (const file of files) dataTransfer.items.add(file);
  input.files = dataTransfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

async function openDialog() {
  await page.getByRole("button", { name: m.upload_files() }).click();
  const dialog = page.getByRole("dialog");
  await expect.element(dialog).toBeVisible();
  return dialog;
}

describe("BlobUpload", () => {
  beforeEach(() => {
    mocks.queueUploads.mockReset();
    mocks.getSummary.mockReset().mockResolvedValue({ limit: null, total_used: 0 });
    mocks.showHeader.set(false);
    mocks.showJobManagerPanel.set(false);
  });

  it("shows the supported formats inside the upload dialog", async () => {
    render(BlobUpload, { collection, currentBlobs: [] });
    const dialog = await openDialog();

    await expect.element(dialog.getByText(m.supported_formats())).toBeVisible();
    await expect.element(dialog.getByText(m.file_format_group_documents())).toBeVisible();
    await expect.element(dialog.getByText(".pdf", { exact: true })).toBeVisible();
    await expect.element(dialog.getByText(".txt", { exact: true })).toBeVisible();
    expect(document.body.textContent).not.toContain("application/pdf");
  });

  it("queues accepted files and closes the dialog", async () => {
    render(BlobUpload, { collection, currentBlobs: [] });
    const dialog = await openDialog();
    const upload = dialog.getByRole("button", { name: m.upload_files() });
    await expect.element(upload).toBeDisabled();

    const pdf = new File(["%PDF"], "report.pdf", { type: "application/pdf" });
    selectFiles([pdf]);
    await expect.element(dialog.getByText("report.pdf")).toBeVisible();
    await expect.element(upload).toBeEnabled();
    await upload.click();

    expect(mocks.queueUploads).toHaveBeenCalledWith("collection-1", [pdf]);
    expect(mocks.showHeader.value).toBe(true);
    expect(mocks.showJobManagerPanel.value).toBe(true);
    await vi.waitFor(() => expect(document.querySelector("[role=dialog]")).toBeNull());
  });

  it("explains skipped files and blocks oversized ones", async () => {
    render(BlobUpload, { collection, currentBlobs: [] });
    const dialog = await openDialog();

    selectFiles([new File(["png"], "photo.png", { type: "image/png" })]);
    await expect
      .element(dialog.getByText(m.upload_skipped_unsupported_files({ fileList: "photo.png" })))
      .toBeVisible();
    await expect.element(dialog.getByRole("button", { name: m.upload_files() })).toBeDisabled();

    selectFiles([new File(["x".repeat(2048)], "big.txt", { type: "text/plain" })]);
    await expect
      .element(
        dialog.getByText(
          m.file_too_large_detail({ fileName: "big.txt", currentSize: "2 KB", maxSize: "1 KB" })
        )
      )
      .toBeVisible();
    await expect.element(dialog.getByRole("button", { name: m.upload_files() })).toBeDisabled();
  });

  it("asks before replacing files that already exist in the collection", async () => {
    render(BlobUpload, { collection, currentBlobs: [existingBlob] });
    const dialog = await openDialog();

    const pdf = new File(["%PDF"], "existing.pdf", { type: "application/pdf" });
    selectFiles([pdf]);
    await dialog.getByRole("button", { name: m.upload_files() }).click();

    const confirmation = page.getByRole("alertdialog");
    await expect.element(confirmation).toBeVisible();
    await expect.element(confirmation.getByText("existing.pdf")).toBeVisible();
    expect(mocks.queueUploads).not.toHaveBeenCalled();

    await confirmation.getByRole("button", { name: m.replace_files() }).click();
    expect(mocks.queueUploads).toHaveBeenCalledWith("collection-1", [pdf]);
  });
});
