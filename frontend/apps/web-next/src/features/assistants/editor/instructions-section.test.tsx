// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { SettingsMarks } from "@/components/composites/settings-rows";
import { renderInApp } from "@/test/render";
import type { Assistant } from "./use-assistant";

const state = vi.hoisted(() => ({ space: null as unknown as Space }));

vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});
vi.mock("./use-assistant", () => ({
  useUpdateAssistant: () => useMutation({ mutationFn: () => Promise.resolve({}) })
}));

import { InstructionsSection } from "./instructions-section";

afterEach(cleanup);

it("keeps the prompt's buttons on the page's gutter where they wrap under the label", () => {
  state.space = makeSpace({ permissions: ["read", "edit"] });
  renderInApp(
    <InstructionsSection
      assistant={
        {
          id: "assistant",
          prompt: { text: "" },
          attachments: [],
          completion_model: null,
          permissions: ["edit"]
        } as unknown as Assistant
      }
    />
  );

  // On a phone's layout the buttons wrap under the label: the ghost buttons' own
  // inset is pulled back, so their icons start on the label's 16 px line.
  const toolbar = screen.getByRole("button", { name: "Visa prompthistorik" }).parentElement!;
  expect(toolbar.classList.contains("phone:-ms-2.5")).toBe(true);
});

it("offers the helper's help with the prompt before its history, where the editor asks for it", () => {
  state.space = makeSpace({ permissions: ["read", "edit"] });
  const assistant = {
    id: "assistant",
    prompt: { text: "" },
    attachments: [],
    completion_model: null,
    permissions: ["edit"]
  } as unknown as Assistant;
  const onAskPrompt = vi.fn();
  renderInApp(<InstructionsSection assistant={assistant} onAskPrompt={onAskPrompt} />);

  const ask = screen.getByRole("button", { name: "Hjälp mig skriva instruktionerna" });
  const history = screen.getByRole("button", { name: "Visa prompthistorik" });
  expect(ask.parentElement).toBe(history.parentElement);
  expect(ask.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(ask);
  expect(onAskPrompt).toHaveBeenCalledOnce();
  cleanup();

  // Not asked for (no helper, or no right to change the prompt): not there, nothing in its place.
  renderInApp(<InstructionsSection assistant={assistant} />);
  expect(screen.queryByRole("button", { name: "Hjälp mig skriva instruktionerna" })).toBeNull();
});

it("offers no help with a prompt a policy sets", () => {
  state.space = makeSpace({ permissions: ["read", "edit"] });
  const assistant = {
    id: "assistant",
    prompt: { text: "Organisationens prompt." },
    attachments: [],
    completion_model: null,
    permissions: ["edit"],
    effective_config: {
      prompt_locked: true,
      models_enforced: false,
      mcp_enforced: false,
      available_models: [],
      default_model: null,
      locked_model: null,
      default_reasoning_effort: null,
      reasoning_effort_user_configurable: true
    }
  } as unknown as Assistant;
  renderInApp(<InstructionsSection assistant={assistant} onAskPrompt={vi.fn()} />);

  expect(screen.getByRole("textbox", { name: "Prompt" })).toHaveProperty("disabled", true);
  expect(screen.queryByRole("button", { name: "Hjälp mig skriva instruktionerna" })).toBeNull();
});

it("marks the instructions while they are marked, beside their label, the field's name unchanged", () => {
  state.space = makeSpace({ permissions: ["read", "edit"] });
  const assistant = {
    id: "assistant",
    prompt: { text: "Svara kort." },
    attachments: [],
    completion_model: null,
    permissions: ["edit"]
  } as unknown as Assistant;
  renderInApp(
    <SettingsMarks marks={{ rows: new Set(["assistant-prompt"]), label: "Ändrad från chatten" }}>
      <InstructionsSection assistant={assistant} />
    </SettingsMarks>
  );

  const field = screen.getByRole("textbox", { name: "Prompt" });
  const block = field.parentElement!;
  expect(within(block).getByText("Ändrad från chatten")).toBeTruthy();
  expect(block.className).toContain("bg-ax-selected");
  cleanup();

  renderInApp(<InstructionsSection assistant={assistant} />);
  expect(screen.queryByText("Ändrad från chatten")).toBeNull();
  expect(screen.getByRole("textbox", { name: "Prompt" }).parentElement!.className).not.toContain(
    "bg-ax-selected"
  );
});
