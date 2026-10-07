import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";
import { EneoError } from "@eneo/eneo-js";
import { withLocale } from "$lib/features/flows/testLocale";
import CreateFlowDialog from "./CreateFlowDialog.svelte";

const goto = vi.fn();
const createFlow = vi.fn(async (name: string) => ({ id: "flow-9", name }));

vi.mock("$app/navigation", () => ({ goto: (...args: unknown[]) => goto(...args) }));
vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    user: { hasPermission: () => true }
  })
}));
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
  it("offers the AI path first and sends the task to the builder page", async () => {
    render(CreateFlowDialog);
    await fireEvent.click(screen.getByRole("button", { name: m.flow_create_button() }));

    // The dialog chooses a path; the task text is written on the builder page.
    expect(screen.queryByRole("textbox")).toBeNull();
    await fireEvent.click(
      screen.getByRole("button", { name: new RegExp(m.flow_create_path_ai_title()) })
    );
    expect(goto).toHaveBeenCalledWith("/spaces/space-1/flows/ai-builder");
  });

  it.each(["sv", "en"] as const)(
    "routes rejected creation through localized errors in %s",
    async (locale) => {
      const restore = withLocale(locale);
      try {
        render(CreateFlowDialog);
        await fireEvent.click(screen.getByRole("button", { name: m.flow_create_button() }));
        await fireEvent.click(
          screen.getByRole("button", { name: new RegExp(m.flow_create_path_manual_title()) })
        );
        await fireEvent.input(screen.getByLabelText(m.name()), { target: { value: "Case flow" } });
        // Mutant: bypass the Flow mapper and show coded backend text at this actual caller.
        for (const [code, expected] of [
          ["flow_run_stale_version", m.flow_error_flow_run_stale_version()],
          ["unmapped_test_code", "Backend detail"],
          [null, m.request_failed()]
        ] as const) {
          createFlow.mockRejectedValueOnce(
            code === null
              ? new Error("Local failure")
              : new EneoError("Backend detail", "RESPONSE", 400, 0, { code })
          );
          await fireEvent.click(
            within(screen.getByRole("dialog")).getByRole("button", {
              name: m.flow_create_path_manual_action()
            })
          );
          await vi.waitFor(() => expect(screen.getByText(expected)).toBeTruthy());
        }
        expect(goto).not.toHaveBeenCalled();
      } finally {
        restore();
      }
    }
  );

  it("creates a named flow on the manual path and opens its editor", async () => {
    render(CreateFlowDialog);
    await fireEvent.click(screen.getByRole("button", { name: m.flow_create_button() }));
    await fireEvent.click(
      screen.getByRole("button", { name: new RegExp(m.flow_create_path_manual_title()) })
    );

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
