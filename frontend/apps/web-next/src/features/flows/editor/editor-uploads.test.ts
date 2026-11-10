// @vitest-environment jsdom
import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { releasableUploads, useEditorUploads } from "./editor-uploads";
import { makeAssistant, makeFlow, makeStep } from "./testing/fixtures";

const remove = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock("@/lib/api/browser", () => ({ browserApi: { DELETE: remove } }));

describe("releasableUploads", () => {
  it("keeps every upload the saved flow or step assistant references", () => {
    const flow = makeFlow({
      steps: [
        makeStep({
          output_mode: "template_fill",
          output_type: "docx",
          output_config: { template_asset_id: "asset-kept" }
        })
      ]
    });
    const assistant = makeAssistant({
      attachments: [{ id: "file-kept", name: "a.txt", size: 1 }] as never
    });
    expect(
      releasableUploads(
        [
          { kind: "template", id: "asset-kept" },
          { kind: "template", id: "asset-dropped" },
          { kind: "file", id: "file-kept" },
          { kind: "file", id: "file-dropped" }
        ],
        { flows: [flow, undefined], assistant }
      )
    ).toEqual([
      { kind: "template", id: "asset-dropped" },
      { kind: "file", id: "file-dropped" }
    ]);
  });
});

describe("useEditorUploads", () => {
  it("keeps an unsaved upload while the step gets another assistant, and releases it when the edit ends", () => {
    const flow = makeFlow({ steps: [makeStep()] });
    let assistantId = "assistant-1";
    const { result, rerender, unmount } = renderHookInApp(() =>
      useEditorUploads(flow, assistantId)
    );
    act(() => result.current.record({ kind: "template", id: "asset-new" }));

    // The flow assistant gives the step its own assistant while the edit is open.
    assistantId = "assistant-2";
    rerender();
    expect(remove).not.toHaveBeenCalled();

    unmount();
    expect(remove).toHaveBeenCalledWith("/api/v1/flows/{id}/template-files/{file_id}/", {
      params: { path: { id: flow.id, file_id: "asset-new" } }
    });
  });
});
