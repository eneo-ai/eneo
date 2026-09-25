import { afterEach, expect, test, vi } from "vitest";
import { assignLocation } from "./navigation";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("navigates the current document to the given URL", () => {
  const assign = vi.fn();
  vi.stubGlobal("window", { location: { assign } });

  assignLocation("https://eneo.example/api/v1/info-blobs/blob-1/original/download/?token=signed");

  expect(assign).toHaveBeenCalledExactlyOnceWith(
    "https://eneo.example/api/v1/info-blobs/blob-1/original/download/?token=signed"
  );
});
