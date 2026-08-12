import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";
import CreateFlowDialog from "./CreateFlowDialog.svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
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
  getFlowsManager: () => ({ createFlow: vi.fn() })
}));
vi.mock("$lib/features/flows/ai-builder/flowAIBuilderSeed", () => ({
  writeAIBuilderSeed: vi.fn()
}));

afterEach(() => {
  cleanup();
});

describe("CreateFlowDialog", () => {
  it("keeps a long prompt inside a scrollable dialog with reachable actions", async () => {
    render(CreateFlowDialog);
    await fireEvent.click(screen.getByRole("button", { name: m.flow_create() }));

    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("max-h-[calc(100dvh-1.5rem)]");
    expect(dialog.className).toContain("overflow-hidden");

    const scrollableBody = dialog.firstElementChild;
    expect(scrollableBody?.className).toContain("overflow-y-auto");

    const prompt = screen.getByLabelText(m.flow_create_prompt_label()) as HTMLTextAreaElement;
    const longPrompt = "Beskriv ett långt flöde. ".repeat(500);
    await fireEvent.input(prompt, { target: { value: longPrompt } });
    expect(prompt.value).toBe(longPrompt);
    expect(prompt.className).toContain("field-sizing-fixed");
    expect(prompt.className).toContain("max-h-[min(20rem,40dvh)]");

    const footer = dialog.querySelector('[data-slot="dialog-footer"]');
    expect(footer?.className).toContain("shrink-0");
    const continueButton = screen.getByRole("button", { name: m.flow_create_continue_ai() });
    expect(continueButton.hasAttribute("disabled")).toBe(false);
    expect(continueButton.className).toContain("w-full");
  });
});
