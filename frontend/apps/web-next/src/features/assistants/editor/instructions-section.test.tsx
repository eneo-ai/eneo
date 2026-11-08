// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { promptGuideAvailabilityQueryOptions } from "@/features/help-assistants/prompt-guide/helper-runs";
import { renderInApp, testQueryClient } from "@/test/render";
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
      promptGuide={false}
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

it("hides an unavailable Promptguide on a phone, where its reason's tooltip cannot be reached", () => {
  state.space = makeSpace({ permissions: ["read", "edit"] });
  const assistant = {
    id: "assistant",
    prompt: { text: "" },
    attachments: [],
    completion_model: null,
    permissions: ["edit"]
  } as unknown as Assistant;
  const guide = (available: boolean) => {
    const queryClient = testQueryClient();
    queryClient.setQueryData(
      promptGuideAvailabilityQueryOptions(browserApi, assistant.id).queryKey,
      available ? { available } : { available, disabled_reason: "no_assignment" }
    );
    renderInApp(<InstructionsSection assistant={assistant} />, { queryClient });
    const button = screen.getByRole("button", { name: /Promptguide/ });
    cleanup();
    return button.parentElement!;
  };

  // Where the layout is not a phone's, the disabled button stays, its reason in the tooltip.
  expect(guide(false).classList.contains("phone:hidden")).toBe(true);
  expect(guide(true).classList.contains("phone:hidden")).toBe(false);
});
