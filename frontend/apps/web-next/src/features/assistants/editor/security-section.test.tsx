// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Assistant } from "./use-assistant";

const state = vi.hoisted(() => ({ space: null as unknown as Space }));
const update = vi.hoisted(() => vi.fn().mockResolvedValue({}));

vi.mock("./use-assistant", () => ({
  useUpdateAssistant: () => useMutation({ mutationFn: (body: unknown) => update(body) })
}));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});

import { SecuritySection } from "./security-section";

afterEach(() => {
  cleanup();
  update.mockReset();
  update.mockResolvedValue({});
});

const assistant = { id: "assistant", data_retention_days: 14 } as Assistant;

function show(space: Space) {
  state.space = space;
  return renderInApp(<SecuritySection assistant={assistant} />);
}

const retention = () =>
  screen.getByRole("spinbutton", { name: "Gallring av konversationshistorik" });

describe("assistant retention", () => {
  it("lets someone who may edit a shared space change it", async () => {
    show(makeSpace({ permissions: ["read", "edit"] }));

    expect(retention().hasAttribute("disabled")).toBe(false);
    fireEvent.change(retention(), { target: { value: "30" } });
    fireEvent.blur(retention());

    await waitFor(() => expect(update).toHaveBeenCalledWith({ data_retention_days: 30 }));
  });

  it("shows it read-only to an assistant editor who may not edit the space", async () => {
    const { container } = show(makeSpace({ permissions: ["read"] }));

    expect((retention() as HTMLInputElement).value).toBe("14");
    expect(retention().hasAttribute("disabled")).toBe(true);
    const hint = screen.getByText("Endast administratörer för utrymmet kan ändra gallringen.");
    expect(retention().getAttribute("aria-describedby")).toContain(hint.id);
    await expectNoAxeViolations(container);
  });

  it("stays editable in a personal space, which has no space administrators", () => {
    show(makeSpace({ permissions: ["read"], overrides: { personal: true } }));

    expect(retention().hasAttribute("disabled")).toBe(false);
    expect(
      screen.queryByText("Endast administratörer för utrymmet kan ändra gallringen.")
    ).toBeNull();
  });
});
