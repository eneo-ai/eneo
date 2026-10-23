import { describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import type { UploadedFile } from "@eneo/eneo-js";
import { createAttachmentManager, matchesUpload, UploadsNotReadyError } from "./AttachmentManager";

vi.mock("$lib/components/toast", () => ({ toast: { error: vi.fn() } }));

type Upload = {
  file: File;
  resolve: (file: UploadedFile) => void;
  reject: (error: Error) => void;
  abort: AbortController;
};

/** An eneo client whose uploads finish only when the test says so. */
function manager(concurrency = 5) {
  const uploads: Upload[] = [];
  const upload = vi.fn(
    ({ file, abortController }: { file: File; abortController: AbortController }) =>
      new Promise<UploadedFile>((resolve, reject) => {
        uploads.push({ file, resolve, reject, abort: abortController });
        abortController.signal.addEventListener("abort", () =>
          reject(new Error("Cancelled after receiving abort signal."))
        );
      })
  );
  const eneo = { files: { upload, delete: vi.fn().mockResolvedValue(undefined) } } as never;
  const instance = createAttachmentManager({ eneo });
  void concurrency;
  return { ...instance, uploads, upload };
}

const file = (name: string) => new File(["x".repeat(10)], name, { type: "text/plain" });
const uploaded = (name: string): UploadedFile =>
  ({ id: `server-${name}`, name, mimetype: "text/plain", size: 10 }) as UploadedFile;

function finish(upload: Upload) {
  upload.resolve(uploaded(upload.file.name));
}

async function settled() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("awaitUploads", () => {
  it("resolves at once when every listed attachment is already uploaded", async () => {
    const { queueValidUploads, state, uploads, awaitUploads } = manager();
    queueValidUploads([file("a.txt")]);
    finish(uploads[0]);
    await settled();
    const [attachment] = get(state.attachments);

    await expect(awaitUploads([attachment.id])).resolves.toEqual([uploaded("a.txt")]);
  });

  it("resolves in the listed order once the last upload completes", async () => {
    const { queueValidUploads, state, uploads, awaitUploads } = manager();
    queueValidUploads([file("a.txt"), file("b.txt")]);
    const ids = get(state.attachments).map((attachment) => attachment.id);
    const ready = awaitUploads(ids);
    let done = false;
    void ready.then(() => (done = true));

    finish(uploads[1]);
    await settled();
    expect(done).toBe(false);

    finish(uploads[0]);
    await expect(ready).resolves.toEqual([uploaded("a.txt"), uploaded("b.txt")]);
  });

  it("rejects when one of the uploads fails, and only then", async () => {
    const { queueValidUploads, state, uploads, awaitUploads } = manager();
    queueValidUploads([file("a.txt"), file("b.txt")]);
    const ids = get(state.attachments).map((attachment) => attachment.id);
    const ready = awaitUploads(ids);

    uploads[0].reject(new Error("boom"));
    await expect(ready).rejects.toBeInstanceOf(UploadsNotReadyError);
    await expect(ready).rejects.toMatchObject({ reason: "failed" });
    expect(get(state.uploadError)).toContain("a.txt");
    // The failed file is gone; the other one is still on its way.
    expect(get(state.attachments).map((attachment) => attachment.file.name)).toEqual(["b.txt"]);
  });

  it("rejects when a listed attachment is removed before it finished", async () => {
    const { queueValidUploads, state, awaitUploads } = manager();
    queueValidUploads([file("a.txt")]);
    const [attachment] = get(state.attachments);
    const ready = awaitUploads([attachment.id]);

    attachment.remove();
    await expect(ready).rejects.toMatchObject({ reason: "failed" });
  });

  it("rejects on an abort signal without cancelling the upload itself", async () => {
    const { queueValidUploads, state, uploads, awaitUploads } = manager();
    queueValidUploads([file("a.txt")]);
    const [attachment] = get(state.attachments);
    const controller = new AbortController();
    const ready = awaitUploads([attachment.id], controller.signal);

    controller.abort();
    await expect(ready).rejects.toMatchObject({ reason: "aborted" });
    expect(uploads[0].abort.signal.aborted).toBe(false);

    // The upload still completes in the composer.
    finish(uploads[0]);
    await settled();
    expect(get(state.attachments)[0].status).toBe("completed");
  });

  it("rejects immediately on an already aborted signal", async () => {
    const { queueValidUploads, state, awaitUploads } = manager();
    queueValidUploads([file("a.txt")]);
    const [attachment] = get(state.attachments);
    const controller = new AbortController();
    controller.abort();

    await expect(awaitUploads([attachment.id], controller.signal)).rejects.toMatchObject({
      reason: "aborted"
    });
  });

  it("lets a failed upload pass unnoticed when nobody is waiting for it", async () => {
    const { queueValidUploads, uploads, state } = manager();
    queueValidUploads([file("a.txt")]);

    uploads[0].reject(new Error("boom"));
    await settled();
    expect(get(state.attachments)).toEqual([]);
    expect(get(state.uploadError)).toContain("a.txt");
  });
});

describe("removing attachments", () => {
  it("removes only the chosen queued file, leaving later queued files to upload", async () => {
    // More files than the upload pool takes at once, so some stay queued.
    const { queueValidUploads, state, uploads } = manager();
    queueValidUploads(["a", "b", "c", "d", "e", "f", "g"].map((name) => file(`${name}.txt`)));
    const queued = get(state.attachments).filter((attachment) => attachment.status === "queued");
    expect(queued.length).toBe(2);

    queued[0].remove();
    for (const upload of uploads.slice(0, 5)) finish(upload);
    await settled();

    const names = get(state.attachments).map((attachment) => attachment.file.name);
    expect(names).not.toContain(queued[0].file.name);
    expect(names).toContain(queued[1].file.name);
    expect(uploads.map((upload) => upload.file.name)).toContain(queued[1].file.name);
  });

  it("drops the sent attachments and keeps the rest", async () => {
    const { queueValidUploads, state, removeUploads } = manager();
    queueValidUploads([file("a.txt"), file("b.txt")]);
    const [first, second] = get(state.attachments);

    removeUploads([first.id]);
    expect(get(state.attachments).map((attachment) => attachment.id)).toEqual([second.id]);
  });
});

describe("duplicate files", () => {
  const picked = (name: string, modified = 1_700_000_000_000) =>
    new File(["x".repeat(10)], name, { type: "text/plain", lastModified: modified });

  it("does not upload a file that is already in the list", () => {
    const { queueValidUploads, state, upload } = manager();
    queueValidUploads([picked("a.txt")]);
    const errors = queueValidUploads([picked("a.txt")]);

    expect(upload).toHaveBeenCalledTimes(1);
    expect(get(state.attachments)).toHaveLength(1);
    expect(errors).toEqual([expect.stringContaining("a.txt")]);
  });

  it("tells several skipped duplicates apart from a changed file of the same name", () => {
    const { queueValidUploads, state, upload } = manager();
    queueValidUploads([picked("a.txt"), picked("b.txt")]);
    queueValidUploads([picked("a.txt"), picked("b.txt"), picked("a.txt", 1_700_000_999_000)]);

    expect(upload).toHaveBeenCalledTimes(3);
    expect(get(state.attachments)).toHaveLength(3);
    expect(get(state.uploadError)).toMatch(/2/);
  });
});

describe("files the conversation already has", () => {
  const stored = (name: string, bytes = 10): UploadedFile =>
    ({
      id: `stored-${name}`,
      name,
      mimetype: "text/plain",
      size: 7,
      original_size: bytes
    }) as UploadedFile;

  it("matches a picked file to a stored one by name, type and original bytes", () => {
    expect(matchesUpload(file("a.txt"), stored("a.txt"))).toBe(true);
    expect(matchesUpload(file("a.txt"), stored("b.txt"))).toBe(false);
    expect(matchesUpload(file("a.txt"), stored("a.txt", 11))).toBe(false);
    expect(matchesUpload(file("a.txt"), { ...stored("a.txt"), mimetype: "text/csv" })).toBe(false);
    // Without a stored original size the text size stands in.
    expect(
      matchesUpload(file("a.txt"), { ...stored("a.txt"), original_size: null, size: 10 })
    ).toBe(true);
  });

  it("attaches a known file again without uploading, and removes it without deleting", async () => {
    const existing = stored("a.txt");
    const eneo = {
      files: { upload: vi.fn(), delete: vi.fn().mockResolvedValue(undefined) }
    } as never;
    const { queueValidUploads, state, awaitUploads } = createAttachmentManager({
      eneo,
      options: { findExisting: (picked) => (picked.name === "a.txt" ? existing : undefined) }
    });

    queueValidUploads([file("a.txt"), file("b.txt")]);
    const [reused, fresh] = get(state.attachments);
    expect(reused).toMatchObject({ status: "completed", reused: true, fileRef: existing });
    expect(fresh.status).toBe("uploading");
    expect(
      (eneo as { files: { upload: ReturnType<typeof vi.fn> } }).files.upload
    ).toHaveBeenCalledTimes(1);
    await expect(awaitUploads([reused.id])).resolves.toEqual([existing]);

    reused.remove();
    await settled();
    expect(
      (eneo as { files: { delete: ReturnType<typeof vi.fn> } }).files.delete
    ).not.toHaveBeenCalled();
    expect(get(state.attachments).map((attachment) => attachment.file.name)).toEqual(["b.txt"]);
  });
});
