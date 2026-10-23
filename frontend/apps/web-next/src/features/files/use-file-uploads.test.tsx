// @vitest-environment jsdom
import { act, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { releasePreviews, UploadsNotReadyError, useFileUploads } from "./use-file-uploads";

const api = vi.hoisted(() => ({ POST: vi.fn(), DELETE: vi.fn() }));
const errors = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/api/toast", () => ({ toastApiError: errors }));
const file = () => new File(["contents"], "notes.txt", { type: "text/plain" });
const ok = () => ({ data: { id: "uploaded-1" }, response: new Response("{}") });

beforeEach(() => {
  api.POST.mockResolvedValue(ok());
  api.DELETE.mockResolvedValue({ data: null, response: new Response(null, { status: 204 }) });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.restoreAllMocks();
});

it.each(["remove", "unmount"] as const)(
  "deletes a completed upload after pending %s",
  async (operation) => {
    let finish!: (response: ReturnType<typeof ok>) => void;
    api.POST.mockReturnValue(
      new Promise<ReturnType<typeof ok>>((resolve) => {
        finish = resolve;
      })
    );
    const { result, unmount } = renderHookInApp(() => useFileUploads({ previews: true }));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.add([file()]);
    });
    if (operation === "remove") act(() => result.current.remove(result.current.files[0]!.key));
    else unmount();
    await act(async () => {
      finish(ok());
      await pending;
    });
    expect(api.DELETE).toHaveBeenCalledExactlyOnceWith("/api/v1/files/{id}/", {
      params: { path: { id: "uploaded-1" } }
    });
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:preview");
    if (operation === "remove") expect(result.current.files).toEqual([]);
  }
);

it("releases previews on failed upload", async () => {
  api.POST.mockRejectedValue(new Error("Upload failed"));
  const { result } = renderHookInApp(() => useFileUploads({ previews: true }));
  await act(() => result.current.add([file()]));
  expect(result.current.files).toEqual([]);
  expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:preview");
  expect(errors).toHaveBeenCalledTimes(1);
});

it("transfers files to a submitted resource without deleting them on unmount", async () => {
  const { result, unmount } = renderHookInApp(() => useFileUploads({ previews: true }));
  await act(() => result.current.add([file()]));
  act(() => {
    releasePreviews(result.current.detach(new Set(["uploaded-1"])));
  });
  unmount();
  expect(api.DELETE).not.toHaveBeenCalled();
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
});

it("restores files after a rejected submit and discards them on cancel", async () => {
  const { result } = renderHookInApp(() => useFileUploads());
  await act(() => result.current.add([file()]));
  act(() => {
    const taken = result.current.detach();
    result.current.restore(taken);
  });
  expect(result.current.files[0]?.fileId).toBe("uploaded-1");
  await act(() => result.current.discard());
  expect(result.current.files).toEqual([]);
  expect(api.DELETE).toHaveBeenCalledTimes(1);
});

it("surfaces backend deletion errors, including resolved HTTP errors", async () => {
  api.DELETE.mockResolvedValue({
    error: { message: "Deletion refused" },
    response: new Response("{}", { status: 403 })
  });
  const { result } = renderHookInApp(() => useFileUploads());
  await act(() => result.current.add([file()]));
  await act(() => result.current.discard());
  expect(errors).toHaveBeenCalledTimes(1);
});

it("keeps a reused server file when it is removed or abandoned", async () => {
  const { result, unmount } = renderHookInApp(() => useFileUploads({ previews: true }));
  act(() => {
    result.current.reuse(file(), { id: "earlier-1" });
    result.current.reuse(file(), { id: "earlier-2" });
  });
  expect(
    result.current.files.map((upload) => [upload.fileId, upload.uploading, upload.reused])
  ).toEqual([
    ["earlier-1", false, true],
    ["earlier-2", false, true]
  ]);
  act(() => result.current.remove(result.current.files[0]!.key));
  unmount();
  expect(api.DELETE).not.toHaveBeenCalled();
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
});

it("remembers when a picked file was last changed", async () => {
  const { result } = renderHookInApp(() => useFileUploads());
  const picked = new File(["contents"], "notes.txt", { type: "text/plain", lastModified: 1234 });
  await act(() => result.current.add([picked]));
  expect(result.current.files[0]?.lastModified).toBe(1234);
});

it("resolves awaited uploads once they are all done, and rejects when one leaves", async () => {
  let finish!: (response: ReturnType<typeof ok>) => void;
  api.POST.mockReturnValueOnce(
    new Promise<ReturnType<typeof ok>>((resolve) => {
      finish = resolve;
    })
  );
  const { result } = renderHookInApp(() => useFileUploads());
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.add([file()]);
    result.current.reuse(file(), { id: "earlier-1" });
  });
  const keys = result.current.files.map((upload) => upload.key);
  const awaited = result.current.awaitUploads(keys);
  let settled = false;
  void awaited.then(() => {
    settled = true;
  });
  await Promise.resolve();
  expect(settled).toBe(false);
  await act(async () => {
    finish(ok());
    await pending;
  });
  expect((await awaited).map((upload) => upload.fileId)).toEqual(["uploaded-1", "earlier-1"]);

  const gone = result.current.awaitUploads(["missing"]);
  await expect(gone).rejects.toBeInstanceOf(UploadsNotReadyError);
  await expect(gone).rejects.toMatchObject({ reason: "failed" });
});

it("rejects awaited uploads when the caller gives up", async () => {
  api.POST.mockReturnValue(new Promise(() => {}));
  const { result } = renderHookInApp(() => useFileUploads());
  act(() => {
    void result.current.add([file()]);
  });
  const controller = new AbortController();
  const awaited = result.current.awaitUploads([result.current.files[0]!.key], controller.signal);
  controller.abort();
  await expect(awaited).rejects.toMatchObject({ reason: "aborted" });
});
