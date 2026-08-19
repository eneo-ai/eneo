import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";
import CreateFlowDialog from "./CreateFlowDialog.svelte";

const goto = vi.fn();
const createFlow = vi.fn(async (name: string) => ({ id: "flow-9", name }));

vi.mock("$app/navigation", () => ({ goto: (...args: unknown[]) => goto(...args) }));
vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: {
        subscribe: (run: (space: { id: string; routeId: string }) => void) => {
          run({ id: "space-1", routeId: "space-1" });
          return () => undefined;
        }
      }
    }
  })
}));
vi.mock("$lib/features/flows/FlowsManager", () => ({
  getFlowsManager: () => ({ createFlow })
}));

afterEach(() => {
  cleanup();
  goto.mockClear();
  createFlow.mockClear();
});

describe("CreateFlowDialog", () => {
  it("creates a named flow and opens its editor", async () => {
    render(CreateFlowDialog);
    await fireEvent.click(screen.getByRole("button", { name: m.flow_create_button() }));
    const action = screen.getByRole("button", { name: m.flow_create_path_manual_action() });
    expect(action.hasAttribute("disabled")).toBe(true);
    await fireEvent.input(screen.getByLabelText(m.name()), {
      target: { value: "  Diarieföring " }
    });
    expect(action.hasAttribute("disabled")).toBe(false);
    await fireEvent.click(action);

    expect(createFlow).toHaveBeenCalledWith("Diarieföring");
    await vi.waitFor(() => expect(goto).toHaveBeenCalledWith("/spaces/space-1/flows/flow-9"));
  });
});
