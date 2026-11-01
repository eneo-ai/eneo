// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { expectNoAxeViolations } from "@/test/axe";
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

import { PublishingSection } from "./publishing-section";

afterEach(cleanup);

const REASON = "Endast ytans administratörer kan växla insikter.";

function show(permissions: string[]) {
  state.space = makeSpace({ permissions: ["read", "edit"] });
  return renderInApp(
    <PublishingSection
      assistant={{ id: "assistant", insight_enabled: false, permissions } as unknown as Assistant}
    />
  );
}

describe("the insights switch", () => {
  it("says in text why it is off for someone who may not change it, not only in a tooltip", async () => {
    const { container } = show(["publish"]);

    expect(screen.getByText(new RegExp(REASON))).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Aktivera insikter" }).hasAttribute("disabled")).toBe(
      true
    );
    // A title attribute is not shown on touch and is not a reliable name or description.
    expect(container.querySelector("[title]")).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("does not repeat the reason for someone who may", () => {
    show(["publish", "insight_toggle"]);

    expect(screen.queryByText(new RegExp(REASON))).toBeNull();
    expect(screen.getByRole("switch", { name: "Aktivera insikter" }).hasAttribute("disabled")).toBe(
      false
    );
  });
});
