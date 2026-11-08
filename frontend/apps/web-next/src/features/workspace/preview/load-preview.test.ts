import { afterEach, expect, it, vi } from "vitest";
import { loadPreview } from "./load-preview";

afterEach(() => {
  vi.unstubAllGlobals();
});

// Originals are served `private, no-cache`; without the BFF in front, only
// this keeps a previewed file out of a shared PC's disk cache.
it("downloads the preview past the browser cache", async () => {
  const fetchMock = vi.fn(async () => new Response("hello"));
  vi.stubGlobal("fetch", fetchMock);
  const signal = new AbortController().signal;

  const content = await loadPreview(
    { id: "file-1", name: "a.txt", mimetype: "text/plain", size: 5 },
    "text",
    "/signed/a.txt",
    signal
  );

  expect(content).toEqual({ kind: "text", text: "hello", truncated: false });
  expect(fetchMock).toHaveBeenCalledWith("/signed/a.txt", { signal, cache: "no-store" });
});
