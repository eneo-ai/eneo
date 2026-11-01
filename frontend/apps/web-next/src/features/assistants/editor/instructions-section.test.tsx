// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
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

  // Below 768 px the buttons wrap under the label: the ghost buttons' own
  // inset is pulled back, so their icons start on the label's 16 px line.
  const toolbar = screen.getByRole("button", { name: "Visa prompthistorik" }).parentElement!;
  expect(toolbar.classList.contains("max-md:-ms-2.5")).toBe(true);
});
