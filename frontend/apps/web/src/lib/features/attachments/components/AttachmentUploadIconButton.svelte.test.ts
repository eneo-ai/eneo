import type { Eneo } from "@eneo/eneo-js";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import type { initAttachmentManager } from "../AttachmentManager";
import AttachmentUploadIconButtonTestHost from "./AttachmentUploadIconButtonTestHost.svelte";

function createEneoMock() {
  return {
    files: {
      upload: vi.fn().mockResolvedValue({ id: "file-1", name: "doc.txt", mimetype: "text/plain" }),
      delete: vi.fn().mockResolvedValue(undefined)
    }
  } as unknown as Eneo;
}

describe("AttachmentUploadIconButton", () => {
  it("accepts the same file again once it has been removed", async () => {
    const eneo = createEneoMock();
    let manager!: ReturnType<typeof initAttachmentManager>;
    const screen = render(AttachmentUploadIconButtonTestHost, {
      eneo,
      onManager: (received) => (manager = received)
    });
    const input = screen.container.querySelector("input[type=file]") as HTMLInputElement;

    const file = new File(["hello"], "doc.txt", { type: "text/plain" });
    const selectFile = () => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);
      input.files = dataTransfer.files;
      input.dispatchEvent(new Event("change"));
    };

    selectFile();
    await vi.waitFor(() => expect(eneo.files.upload).toHaveBeenCalledTimes(1));
    // The input must be reset after queueing: a file input keeps its value,
    // and the browser never fires `change` when the user picks the same file
    // again, so the upload would silently do nothing.
    expect(input.value).toBe("");

    // Picked again while still attached: skipped, not uploaded twice.
    selectFile();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(eneo.files.upload).toHaveBeenCalledTimes(1);
    expect(get(manager.state.uploadError)).toContain("doc.txt");

    await vi.waitFor(() => expect(get(manager.state.attachments)[0].status).toBe("completed"));
    get(manager.state.attachments)[0].remove();
    await vi.waitFor(() => expect(get(manager.state.attachments)).toHaveLength(0));
    selectFile();
    await vi.waitFor(() => expect(eneo.files.upload).toHaveBeenCalledTimes(2));
  });
});
