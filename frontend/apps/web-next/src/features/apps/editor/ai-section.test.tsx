// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { App } from "../apps";

const update = vi.hoisted(() => vi.fn().mockResolvedValue({}));
vi.mock("./use-app", () => ({
  useUpdateApp: () => useMutation({ mutationFn: (body: unknown) => update(body) })
}));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    routeId: "space-1",
    space: {
      transcription_models: [],
      completion_models: [
        {
          id: "gpt-4o",
          name: "gpt-4o",
          nickname: "GPT-4o",
          org: "OpenAI",
          max_input_tokens: 128_000,
          supported_model_kwargs: { temperature: { supported: true, minimum: 0, maximum: 2 } }
        }
      ]
    }
  })
}));
// The autosave contract: the save itself, its result passed through.
vi.mock("@/components/composites/use-autosave", () => ({
  useAutosave: () => (operation: () => Promise<unknown>) => operation()
}));

import { AiSection } from "./ai-section";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => {
  cleanup();
  update.mockClear();
});

const app = {
  id: "app-1",
  input_fields: [{ type: "text-field", description: null }],
  completion_model: { id: "gpt-4o" },
  completion_model_kwargs: {},
  transcription_model: null
} as unknown as App;

async function chooseBehaviour(name: string) {
  fireEvent.keyDown(await screen.findByRole("combobox", { name: "Modellbeteende" }), {
    key: "Enter"
  });
  fireEvent.click(await screen.findByRole("option", { name }));
}

const savedKwargs = () =>
  update.mock.calls.map(
    ([body]) => (body as { completion_model_kwargs: unknown }).completion_model_kwargs
  );

describe("the app editor's model behaviour", () => {
  it("saves a preset as soon as it is chosen", async () => {
    renderInApp(<AiSection app={app} />);
    await chooseBehaviour("Kreativ");
    await waitFor(() => expect(savedKwargs()).toEqual([{ temperature: 1.25 }]));
  });

  it("saves a typed custom temperature once, when its field is left", async () => {
    renderInApp(<AiSection app={app} />);
    await chooseBehaviour("Anpassad");
    // Choosing custom saves its starting temperature at once.
    await waitFor(() => expect(savedKwargs()).toEqual([{ temperature: 1 }]));

    const temperature = screen.getByLabelText("Temperatur");
    fireEvent.change(temperature, { target: { value: "0.7" } });
    fireEvent.change(temperature, { target: { value: "0.75" } });
    expect(update).toHaveBeenCalledTimes(1);

    fireEvent.blur(temperature);
    await waitFor(() => expect(savedKwargs()).toEqual([{ temperature: 1 }, { temperature: 0.75 }]));
  });
});
