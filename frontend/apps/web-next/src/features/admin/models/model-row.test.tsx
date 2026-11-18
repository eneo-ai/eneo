// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { AdminModel } from "./models";
import { ModelRow } from "./model-row";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

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
