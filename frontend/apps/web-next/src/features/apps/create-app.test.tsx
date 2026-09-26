// @vitest-environment jsdom
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderInApp, testAppContext } from "@/test/render";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return { useSpace: () => ({ space: makeSpace(), routeId: "space-1", can: () => true }) };
});

import { CreateAppButton } from "./create-app";

describe("CreateAppButton", () => {
  it("names the split button's menu after what it offers", () => {
    renderInApp(<CreateAppButton />, {
      appContext: testAppContext({ settings: { using_templates: true } })
    });

    const more = screen.getByRole("button", { name: "Fler sätt att skapa" });
    fireEvent.keyDown(more, { key: "Enter" });
    const menu = screen.getByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent?.trim())
    ).toEqual(["Börja med en mall..."]);
  });
});
