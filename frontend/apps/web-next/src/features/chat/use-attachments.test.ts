// @vitest-environment jsdom
import { act } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { renderHookInApp, testAppContext } from "@/test/render";
import { useAttachments } from "./use-attachments";

const api = vi.hoisted(() => ({ POST: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), info: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

beforeEach(() => {
  api.POST.mockResolvedValue({ data: { id: "uploaded-1" }, response: new Response("{}") });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});
afterEach(() => {
  vi.resetAllMocks();
  vi.restoreAllMocks();
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  allowedAttachments: { accepted_file_types: [], limit: { max_files: 1, max_size: 1000 } }
};
const appContext = testAppContext({
  limits: {
    attachments: {
      formats: [{ mimetype: "text/plain", extensions: ["txt"], size: 1000, vision: false }]
    }
  }
});
const text = (name: string) => new File(["x"], name, { type: "text/plain" });

it("holds the file limit when two additions land before a render", async () => {
  const { result } = renderHookInApp(() => useAttachments(partner), { appContext });
  // Two dropped folders whose reads finish in the same task: both reach the
  // same render's addFiles.
  const { addFiles } = result.current;

  await act(() => Promise.all([addFiles([text("first.txt")]), addFiles([text("second.txt")])]));

  expect(result.current.attachments.map((attachment) => attachment.name)).toEqual(["first.txt"]);
  expect(api.POST).toHaveBeenCalledTimes(1);
  expect(toast.error).toHaveBeenCalledWith("Du kan bifoga högst 1 filer åt gången.");
});
