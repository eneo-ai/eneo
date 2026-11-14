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

function show(permissions: string[], assistant: Partial<Assistant> = {}) {
  state.space = makeSpace({ permissions: ["read", "edit"] });
  return renderInApp(
    <PublishingSection
      assistant={
        {
          id: "assistant",
          insight_enabled: false,
          permissions,
          ...assistant
        } as unknown as Assistant
      }
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

describe("the switch that makes an assistant available to other clients", () => {
  const NAME = "Gör tillgänglig";
  const ADMINS_ONLY =
    "Endast ytans administratörer kan ändra om assistenten är tillgänglig för andra klienter.";

  it("shows the stored choice to a space admin, who may change it", async () => {
    const { container } = show(["publish", "insight_toggle"], { external_clients_enabled: true });

    const toggle = screen.getByRole("switch", { name: NAME });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(toggle.hasAttribute("disabled")).toBe(false);
    expect(screen.queryByText(new RegExp(ADMINS_ONLY))).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("says in text why it is off for someone who may not change it", async () => {
    const { container } = show(["publish"]);

    const toggle = screen.getByRole("switch", { name: NAME });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(toggle.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(new RegExp(ADMINS_ONLY))).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("is not offered for a Help Assistant, which is never asked from another client", () => {
    show(["publish", "insight_toggle"], { is_help_assistant: true });

    expect(screen.queryByRole("switch", { name: NAME })).toBeNull();
    expect(screen.getByRole("switch", { name: "Aktivera insikter" })).toBeTruthy();
  });
});
