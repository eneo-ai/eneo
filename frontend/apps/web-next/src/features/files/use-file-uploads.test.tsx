// @vitest-environment jsdom
import { act, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { useFileUploads, releasePreviews } from "./use-file-uploads";

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
