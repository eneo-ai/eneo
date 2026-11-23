// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { AdminModel } from "./models";
import { ModelRow } from "./model-row";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

it.each([
  [true, true, true],
  [false, false, false],
  // Marked, but its provider can no longer carry live text: not a capability now.
  [true, false, false]
])("marks live text among the capabilities: marked %s, streams %s", (marked, streams, on) => {
  renderInApp(
    <ModelRow
      model={
        {
          id: "t1",
          name: "pianissimo-sv",
          supports_realtime: marked,
          streams_live: streams
        } as AdminModel
      }
      kind="transcription"
      layout="list"
      classifications={[]}
      securityEnabled={false}
      onAction={vi.fn()}
    />
  );
  const capabilities = screen.queryByRole("list", { name: "Funktioner" });
  expect(capabilities?.textContent ?? "").toBe(on ? "Livetext" : "");
});

it("locks a historical migrated model even when rendered directly", () => {
  const model = {
    id: "old",
    name: "gpt-4o",
    nickname: "Old model",
    is_org_enabled: false,
    is_locked: false,
    migrated_to_model_id: "replacement"
  } as AdminModel;
  renderInApp(
    <ModelRow
      model={model}
      kind="completion"
      layout="list"
      classifications={[]}
      securityEnabled={false}
      onAction={vi.fn()}
    />
  );
  const toggle = screen.getByRole("switch", { name: "Aktivera Old model" });
  expect(toggle.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(toggle);
  expect(api.POST).not.toHaveBeenCalled();
});
