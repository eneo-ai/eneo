// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { MCP_KEY } from "@/features/admin/mcp/mcp";
import { MODELS_KEY, type AdminModel } from "./models";
import { ModelRow } from "./model-row";

const api = vi.hoisted(() => ({
  POST: vi.fn(() => Promise.resolve({ data: {}, response: new Response("{}") }))
}));
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

it("switching a forecast model off also refreshes the Functions page and the spaces it serves", async () => {
  const model = { id: "f1", name: "default", nickname: "Timestral", is_org_enabled: true };
  const { queryClient } = renderInApp(
    <ModelRow
      model={model as AdminModel}
      kind="forecast"
      layout="list"
      classifications={[]}
      securityEnabled={false}
      onAction={vi.fn()}
    />
  );
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  fireEvent.click(screen.getByRole("switch", { name: "Aktivera Timestral" }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: MCP_KEY }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: MODELS_KEY });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["spaces"] });
});
